# Data Structures and Algorithms

## Arrays and Memory

Arrays are the most fundamental data structure. Understanding how they work
in memory is essential for everything that follows.

### Concept: Arrays
An array is a contiguous block of memory storing elements of the same type.
Elements are accessed by index in O(1) time: address = base + index × size.

Key properties: fixed size, O(1) random access, O(n) insert/delete, cache-friendly.

### Concept: Memory Layout
An integer array starting at 0x1000 with 4-byte elements has element[3] at 0x100C.
This direct address computation is why array access is O(1).

### Problem: Two Sum
Given an array of integers and a target sum, find two numbers that add up to
the target. Return their indices.

## Sorting Algorithms

<!-- prerequisite: Arrays and Memory -->

Sorting arranges elements in a specific order. It's one of the most studied
problems because it appears everywhere and illustrates fundamental techniques.

### Concept: Comparison-Based Sorting
Any comparison-based sort requires Ω(n log n) comparisons in the worst case.
Merge sort and heapsort achieve this bound.

### Concept: Stability
A stable sort preserves relative order of equal elements. Stable: merge sort,
insertion sort. Unstable: quicksort, heapsort.

### Example: Merge Sort Trace
[38, 27, 43, 3, 9, 82, 10]
→ [38, 27, 43, 3] [9, 82, 10]
→ [38, 27] [43, 3] [9, 82] [10]
→ [27, 38] [3, 43] [9, 82] [10]
→ [3, 27, 38, 43] [9, 10, 82]
→ [3, 9, 10, 27, 38, 43, 82]

### Problem: Sort Colors
Given an array with values 0, 1, 2 (red, white, blue), sort in-place in one pass.

## Binary Search

<!-- prerequisite: Sorting Algorithms -->

Binary search eliminates half the search space at each step.

### Concept: Binary Search
Find a target in a sorted array by comparing to the middle element.
If less, search left; if greater, search right. O(log n).

### Concept: Search Space Reduction
The principle extends beyond arrays: binary search on the answer (parametric
search), bisection for root finding, boundary finding in monotonic predicates.

### Example: Binary Search Step-by-Step
Array: [2, 5, 8, 12, 16, 23, 38, 56, 72, 91], Target: 23
Step 1: mid=4 → 16 < 23, go right
Step 2: mid=7 → 56 > 23, go left
Step 3: mid=5 → 23 = 23, found!

### Problem: Search in Rotated Array
A sorted array was rotated at an unknown pivot: [4,5,6,7,0,1,2].
Find a target in O(log n).

## Recursion

<!-- prerequisite: Arrays and Memory -->

Recursion solves problems by breaking them into smaller instances.

### Concept: Recursion
A recursive function has: (1) a base case, (2) a recursive case that reduces
the problem, (3) combination of subresults. The call stack manages state.

### Concept: Divide and Conquer
Divide into subproblems, conquer recursively, combine results. The Master
Theorem gives complexity: T(n) = aT(n/b) + O(n^d).

### Problem: Maximum Subarray
Find the contiguous subarray with the largest sum using divide and conquer.
