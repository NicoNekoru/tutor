# Data Structures and Algorithms

## Arrays and Memory

Arrays are the most fundamental data structure in computer science.
Understanding how they work in memory is essential for everything that follows.

### Concept: Arrays
An array is a contiguous block of memory that stores elements of the same type.
Elements are accessed by index in O(1) time because the address of any element
can be computed directly: base_address + index × element_size.

Key properties:
- Fixed size (in most languages)
- O(1) random access
- O(n) insertion/deletion (requires shifting)
- Cache-friendly due to spatial locality

### Concept: Memory Layout
In memory, an array occupies a contiguous region. If an integer array starts at
address 0x1000 and each integer is 4 bytes, then element[3] is at 0x100C.
This direct address computation is why array access is O(1).

### Problem: Array Rotation
Given an array of n integers, rotate the array to the right by k steps.
For example, [1,2,3,4,5] rotated by 2 gives [4,5,1,2,3].

### Problem: Two Sum
Given an array of integers and a target sum, find two numbers that add up to the target.
Return the indices of the two numbers.

## Sorting Algorithms

<!-- prerequisite: Arrays and Memory -->

Sorting is the problem of arranging elements in a specific order. It's one of
the most studied problems in computer science because it appears everywhere
and its solutions illustrate fundamental algorithmic techniques.

### Concept: Comparison-Based Sorting
A comparison-based sorting algorithm determines order by comparing pairs of elements.
The fundamental theorem: any comparison-based sort requires Ω(n log n) comparisons
in the worst case. This means algorithms like merge sort and heapsort are
asymptotically optimal.

### Concept: Stability in Sorting
A sorting algorithm is stable if it preserves the relative order of elements
with equal keys. For example, if you sort students by grade and two students
both have a B, a stable sort keeps them in their original relative order.

Stable algorithms: merge sort, insertion sort, Tim sort.
Unstable algorithms: quicksort, heapsort, selection sort.

### Example: Merge Sort Trace
Sorting [38, 27, 43, 3, 9, 82, 10]:

Step 1 (divide): [38, 27, 43, 3] and [9, 82, 10]
Step 2 (divide): [38, 27] [43, 3] [9, 82] [10]
Step 3 (divide): [38] [27] [43] [3] [9] [82] [10]
Step 4 (merge):  [27, 38] [3, 43] [9, 82] [10]
Step 5 (merge):  [3, 27, 38, 43] [9, 10, 82]
Step 6 (merge):  [3, 9, 10, 27, 38, 43, 82]

### Problem: Sort Colors
Given an array with n objects colored red, white, or blue (represented as 0, 1, 2),
sort them in-place so that objects of the same color are adjacent, in the order
red, white, blue. Can you solve it in one pass?

## Binary Search

<!-- prerequisite: Sorting Algorithms -->

Binary search is the quintessential divide-and-conquer algorithm. It requires
a sorted input and eliminates half the search space at each step.

### Concept: Binary Search
Binary search finds a target value in a sorted array by repeatedly comparing
the target to the middle element. If the target is less than the middle,
search the left half; if greater, search the right half.

Time complexity: O(log n)
Space complexity: O(1) iterative, O(log n) recursive

The key insight: each comparison eliminates exactly half of the remaining
elements. After k comparisons, at most n/2^k elements remain.

### Concept: Search Space Reduction
The power of binary search comes from its search space reduction property.
This principle extends beyond sorted arrays:
- Binary search on the answer (parametric search)
- Bisection method for root finding
- Finding the boundary between true/false in a monotonic predicate

### Example: Binary Search Step-by-Step
Array: [2, 5, 8, 12, 16, 23, 38, 56, 72, 91]
Target: 23

Step 1: low=0, high=9, mid=4 → arr[4]=16 < 23, search right
Step 2: low=5, high=9, mid=7 → arr[7]=56 > 23, search left
Step 3: low=5, high=6, mid=5 → arr[5]=23 = 23, found!

### Problem: Search in Rotated Sorted Array
A sorted array has been rotated at some unknown pivot. For example,
[4,5,6,7,0,1,2] was originally [0,1,2,4,5,6,7]. Given a target value,
find its index in O(log n) time, or return -1 if not found.

### Problem: Find First and Last Position
Given a sorted array and a target value, find the first and last positions
where the target appears. Return [-1, -1] if the target is not found.
Solve in O(log n) time.

## Recursion and Divide-and-Conquer

<!-- prerequisite: Arrays and Memory -->

Recursion is a method of solving problems by breaking them into smaller
instances of the same problem. Divide-and-conquer is the algorithmic
paradigm built on this idea.

### Concept: Recursion
A recursive function calls itself with a smaller input and has a base case
that stops the recursion. Every recursive solution has three parts:
1. Base case: the simplest instance that can be solved directly
2. Recursive case: break the problem into smaller subproblems
3. Combination: merge subproblem solutions into the final answer

The call stack manages the state of each recursive call. Stack overflow
occurs when recursion is too deep (typically >10,000 frames).

### Concept: Divide and Conquer
Divide and conquer solves a problem by:
1. Dividing it into smaller subproblems (usually of equal size)
2. Conquering each subproblem recursively
3. Combining the results

Classic examples: merge sort, quicksort, binary search, Strassen's
matrix multiplication, closest pair of points.

The Master Theorem gives the time complexity for many D&C recurrences:
T(n) = aT(n/b) + O(n^d)

### Problem: Maximum Subarray
Find the contiguous subarray within an array that has the largest sum.
Solve using divide and conquer in O(n log n) time.
