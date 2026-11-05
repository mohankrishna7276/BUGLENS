"""False-positive probe: syntactically valid, slightly tricky programs that should produce NO
warnings/errors from the static analyzer.   Usage: python tests/run_false_positive_probe.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modules.analyzer import analyze  # noqa: E402

valid = {
"Java": ['''package demo;
import java.util.List;
import java.util.ArrayList;

/** Doc comment */
public class Shape
{
    private final int size;
    @Override
    public String toString()
    {
        return "Shape(" + size + ")";
    }
    public Shape(int size) { this.size = size; }
    public static void main(String[] args) throws Exception
    {
        List<Integer> xs = new ArrayList<>();
        xs.add(1);
        String msg = xs.size() > 0
            ? "non-empty"
            : "empty";
        for (int i = 0; i < xs.size(); i++)
            System.out.println(xs.get(i));
        if (msg.equals("x")) System.out.println("x");
        else System.out.println("y");
        int[] a = {1,
                   2,
                   3};
        switch (a[0]) {
            case 1:
                break;
            default:
                break;
        }
        while (true) { break; }
        do { a[0]++; } while (a[0] < 3);
        String s = "has ; and // and { inside";
    }
}
'''],
"C": ['''#include <stdio.h>
#include <stdlib.h>
#define MAX 10
typedef struct {
    int x;
    int y;
} Point;

static int add(int a,
               int b)
{
    return a + b;
}

int main(void) {
    int arr[MAX];
    char buf[20];
    Point p = {1, 2};
    if (scanf("%d %s", &arr[0], buf) != 2)
        return 1;
    for (int i = 0; i < MAX; i++) arr[i] = i;
    while ((p.x = getchar()) != EOF) { if (p.x == 'a') break; }
    printf("%d %s\\n", add(arr[0],
                          arr[1]), buf);
    /* comment without semicolon */
    // another comment
    return 0;
}
'''],
"JavaScript": ['''const add = (a, b) => a + b
let x = 1
function f(a, b) {
  return a === b
}
const obj = {
  a: 1,
  b: [1, 2, 3],
}
const y = x
  ? 1
  : 2
console.log(`template ${x} = ok`, add(1, 2), f(1, 1), obj, y)
for (let i = 0; i < 3; i++) { x += i }
const z = 5; let w = z + 1;
'''],
"Python": ['''import os, sys
from math import *
class A:
    def m(self, x, y=2):
        return x + y
def f(*args, **kw):
    return len(args)
a = A()
print(a.m(1), f(1,2,3), [i for i in range(3)], {k: v for k, v in zip("ab", [1, 2])})
try:
    1/1
except ValueError as e:
    print(e)
with open(__file__) as fh:
    data = fh.read()
q = [1, 2]
while q:
    q.pop()
lam = lambda z: z * 2
print(lam(2))
''']}

failures = 0
for lang, snippets in valid.items():
    for s in snippets:
        fs = [f for f in analyze(s, lang) if f["severity"] != "info"]
        status = "PASS" if not fs else "FAIL"
        failures += bool(fs)
        print(f"{lang:<11} {status}  {fs or 'no findings'}")
print(f"\nFalse-positive probe: {sum(len(v) for v in valid.values()) - failures}/{sum(len(v) for v in valid.values())} valid programs clean")
sys.exit(1 if failures else 0)
