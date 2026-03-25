# Course Format Guide

This file documents the markdown format used by `rlm-ws ingest`.

## Structure

A course is written as one or more `.md` files inside the `content/` directory.
Headings define the hierarchy:

```
# Module Name          ← top-level grouping
## Lesson Name         ← a teachable unit
### Concept: Name      ← a single idea the student should learn
### Problem: Name      ← an exercise or question
### Example: Name      ← a worked example or walkthrough
```

## Lesson Body

Prose text between `## Lesson` and the first `###` heading becomes the lesson
body — introductory material that sets context before the concepts/problems.

## Prerequisites

Add a comment anywhere in a lesson to declare it depends on another lesson:

```
<!-- prerequisite: Other Lesson Name -->
```

The name must match another `## Lesson Name` heading exactly. Prerequisites
are resolved across all files in the `content/` directory.

## Tips

- One file per module works well, or one big file is fine too.
- Files are processed alphabetically, so prefix with `01-`, `02-`, etc. to
  control ordering.
- Keep concept definitions focused — one idea per `### Concept:` block.
- Problems should be self-contained: state the input, expected output, and
  constraints.
- Examples work best as step-by-step traces showing how an algorithm or
  technique applies to concrete input.

## Example

```markdown
# Algorithms

## Sorting

Sorting is the problem of arranging elements in a specific order.

### Concept: Comparison-Based Sorting
A comparison-based sort determines order by comparing pairs of elements.
Any comparison-based sort requires Ω(n log n) comparisons in the worst case.

### Problem: Sort an Array
Given an unsorted array of integers, sort it in ascending order.

### Example: Merge Sort Trace
Input: [38, 27, 43, 3]
Split: [38, 27] and [43, 3]
Split: [38] [27] [43] [3]
Merge: [27, 38] [3, 43]
Merge: [3, 27, 38, 43]

## Binary Search

<!-- prerequisite: Sorting -->

### Concept: Binary Search
Binary search finds a target in a sorted array by halving the search space.
Time: O(log n). Requires sorted input.

### Problem: Find Element
Given a sorted array and a target, return the index or -1 if not found.
```

Run `rlm-ws ingest content/` to parse these files into the workspace.
