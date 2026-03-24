# Data Structures

## Arrays

An array is a contiguous block of memory that stores elements of the same type. Arrays provide O(1) random access by index, making them the most fundamental data structure.

### Concept: Arrays
An array stores a fixed-size sequential collection of elements of the same type. Elements are accessed by their index (position), starting from 0. The key property is O(1) random access — given an index, you can read or write the element in constant time because the memory address can be computed directly.

### Concept: Array Indexing
Array indexing converts a logical position (index) into a physical memory address using the formula: address = base + index × element_size. This is why arrays are zero-indexed in most languages — the first element is at offset 0.

### Problem: Find Maximum
Given an array of integers, find and return the maximum value. What is the time complexity of your solution?

### Example: Linear Search
To find an element in an unsorted array, check each element sequentially:
1. Start at index 0
2. Compare each element with the target
3. If found, return the index
4. If the end is reached, the element is not present
Time complexity: O(n)

## Sorting

Sorting arranges elements in a specific order (usually ascending). Efficient sorting is a prerequisite for many algorithms, including binary search.

<!-- prerequisite: Arrays -->

### Concept: Comparison Sorting
Comparison-based sorting algorithms determine order by comparing pairs of elements. The theoretical lower bound for comparison sorting is O(n log n). Common algorithms: merge sort, quicksort, heapsort.

### Concept: Sorting Stability
A sorting algorithm is stable if elements with equal keys maintain their relative order from the input. Merge sort is stable; quicksort is not (in its standard form).

### Problem: Sort an Array
Implement a function that sorts an array of integers in ascending order. Analyze the time and space complexity of your implementation.

### Example: Merge Sort Walkthrough
Array: [38, 27, 43, 3, 9, 82, 10]
Split: [38, 27, 43, 3] and [9, 82, 10]
Split: [38, 27] [43, 3] [9, 82] [10]
Split: [38] [27] [43] [3] [9] [82] [10]
Merge: [27, 38] [3, 43] [9, 82] [10]
Merge: [3, 27, 38, 43] [9, 10, 82]
Merge: [3, 9, 10, 27, 38, 43, 82]

## Binary Search

Binary search is an efficient algorithm for finding an element in a sorted array by repeatedly dividing the search space in half.

<!-- prerequisite: Sorting -->

### Concept: Binary Search
Binary search works on sorted arrays. It compares the target with the middle element: if equal, found; if less, search the left half; if greater, search the right half. Each step eliminates half the remaining elements, giving O(log n) time complexity.

### Concept: Loop Invariants
A loop invariant is a condition that is true before and after each iteration of a loop. For binary search, the invariant is: "if the target exists in the array, it exists within the current search bounds [low, high]." Maintaining this invariant ensures correctness.

### Problem: Binary Search Implementation
Implement binary search for a sorted array of integers. Handle the case where the target is not present. What happens if the array is not sorted?

### Problem: First Occurrence
Given a sorted array that may contain duplicates, find the index of the first occurrence of a target value. How does this differ from standard binary search?

### Example: Binary Search Step-by-Step
Array: [2, 5, 8, 12, 16, 23, 38, 56, 72, 91]
Target: 23
Step 1: low=0, high=9, mid=4 → arr[4]=16 < 23 → low=5
Step 2: low=5, high=9, mid=7 → arr[7]=56 > 23 → high=6
Step 3: low=5, high=6, mid=5 → arr[5]=23 = 23 → Found at index 5!

# Linked Lists

## Singly Linked Lists

A linked list is a data structure where elements (nodes) are connected via pointers. Unlike arrays, linked lists do not require contiguous memory.

### Concept: Linked List Nodes
Each node in a singly linked list contains two fields: the data value, and a pointer (reference) to the next node. The last node points to null. The list is accessed through a head pointer.

### Concept: Linked List vs Array Tradeoffs
Arrays: O(1) access, O(n) insertion/deletion, contiguous memory.
Linked lists: O(n) access, O(1) insertion/deletion (given position), non-contiguous memory.
Choose arrays when you need random access; choose linked lists when you need frequent insertions/deletions.

### Problem: Reverse a Linked List
Given the head of a singly linked list, reverse the list and return the new head. Implement both iterative and recursive solutions.

### Example: List Reversal
Original: 1 → 2 → 3 → 4 → null
Step 1: prev=null, curr=1 → 1.next=null, prev=1, curr=2
Step 2: prev=1, curr=2 → 2.next=1, prev=2, curr=3
Step 3: prev=2, curr=3 → 3.next=2, prev=3, curr=4
Step 4: prev=3, curr=4 → 4.next=3, prev=4, curr=null
Result: 4 → 3 → 2 → 1 → null
