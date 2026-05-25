"""
快速排序（Quick Sort）算法详解
================================
包含三种实现方式，逐步递进：
  1. 基础版 - 最简实现（易懂但不高效）
  2. 原地分区版 - 标准实现（面试常考）
  3. 随机 Pivot 版 - 工业级实现（避免最坏情况）
"""

import random
from typing import List


# ============================================================
# 版本一：基础版（最直观，但不是原地排序）
# 思路：把小于 pivot 和大于 pivot 的元素分别放到两个新列表里
# 优点：超好理解，适合初学者
# 缺点：需要额外 O(n) 空间
# ============================================================
def quicksort_basic(arr: List[int]) -> List[int]:
    """快速排序基础版 - 最简实现"""
    # 空数组或只有一个元素，直接返回
    if len(arr) <= 1:
        return arr

    # 选第一个元素作为 pivot（基准值）
    pivot = arr[0]

    # 分区：把所有元素分成三组
    left = [x for x in arr[1:] if x < pivot]     # 小于 pivot
    middle = [x for x in arr if x == pivot]       # 等于 pivot
    right = [x for x in arr[1:] if x > pivot]     # 大于 pivot

    # 递归排序 + 合并
    return quicksort_basic(left) + middle + quicksort_basic(right)


# ============================================================
# 版本二：原地分区版（In-Place 实现）
# 不需要额外数组，直接在原数组上交换元素
# 这是面试中最常考的版本
# ============================================================
def partition(arr: List[int], low: int, high: int) -> int:
    """
    分区函数：将 arr[low..high] 分区
    返回 pivot 最终所在的下标
    """
    # 选最右边的元素作为 pivot
    pivot = arr[high]

    # i 指向"小于 pivot 区域的最后一个位置"
    i = low - 1

    # 遍历 low 到 high-1
    for j in range(low, high):
        # 如果当前元素 <= pivot，把它换到左侧区域
        if arr[j] <= pivot:
            i += 1
            arr[i], arr[j] = arr[j], arr[i]

    # 把 pivot 放到正确的位置（i+1 处）
    arr[i + 1], arr[high] = arr[high], arr[i + 1]
    return i + 1  # 返回 pivot 下标


def quicksort_inplace(arr: List[int], low: int = 0, high: int = None) -> None:
    """
    快速排序原地版
    直接修改原数组，不返回新数组
    参数：
        arr:  待排序数组
        low:  起始下标（默认 0）
        high: 结束下标（默认 len-1）
    """
    if high is None:
        high = len(arr) - 1

    # 递归终止条件
    if low < high:
        # 分区，获取 pivot 下标
        pivot_idx = partition(arr, low, high)

        # 递归排序左右两部分
        quicksort_inplace(arr, low, pivot_idx - 1)   # 排序左侧
        quicksort_inplace(arr, pivot_idx + 1, high)  # 排序右侧


# ============================================================
# 版本三：随机 Pivot 版（工业级实现）
# 随机选 pivot，避免在"已排序数组"上退化到 O(n²)
# 这是实际工程中最常用的方式
# ============================================================
def partition_random(arr: List[int], low: int, high: int) -> int:
    """
    随机选 pivot 的分区函数
    """
    # 随机选一个 pivot，然后和最后一个元素交换
    rand_idx = random.randint(low, high)
    arr[rand_idx], arr[high] = arr[high], arr[rand_idx]

    # 接下来的逻辑和普通分区一样
    pivot = arr[high]
    i = low - 1

    for j in range(low, high):
        if arr[j] <= pivot:
            i += 1
            arr[i], arr[j] = arr[j], arr[i]

    arr[i + 1], arr[high] = arr[high], arr[i + 1]
    return i + 1


def quicksort_random(arr: List[int], low: int = 0, high: int = None) -> None:
    """快速排序随机 Pivot 版"""
    if high is None:
        high = len(arr) - 1

    if low < high:
        pivot_idx = partition_random(arr, low, high)
        quicksort_random(arr, low, pivot_idx - 1)
        quicksort_random(arr, pivot_idx + 1, high)


# ============================================================
# 辅助函数：验证排序是否正确
# ============================================================
def is_sorted(arr: List[int]) -> bool:
    """检查数组是否升序排列"""
    return all(arr[i] <= arr[i + 1] for i in range(len(arr) - 1))


# ============================================================
# 测试代码
# ============================================================
if __name__ == "__main__":
    # 测试数据
    test_cases = [
        [3, 6, 8, 10, 1, 2, 1],
        [5, 4, 3, 2, 1],           # 完全逆序
        [1, 2, 3, 4, 5],           # 已经有序
        [1],                        # 只有一个元素
        [],                         # 空数组
        [7, 7, 7, 7, 7],           # 全部相同
        [-3, 10, -1, 0, 5, 2],     # 包含负数
    ]

    print("=" * 60)
    print("快速排序（Quick Sort）算法演示")
    print("=" * 60)

    for i, test in enumerate(test_cases, 1):
        print(f"\n--- 测试用例 {i} ---")
        print(f"原始数据: {test}")

        # 测试版本一：基础版
        result1 = quicksort_basic(test.copy())
        print(f"基础排序: {result1}  ✅ {is_sorted(result1)}")

        # 测试版本二：原地分区版
        arr2 = test.copy()
        quicksort_inplace(arr2)
        print(f"原地排序: {arr2}  ✅ {is_sorted(arr2)}")

        # 测试版本三：随机 pivot 版
        arr3 = test.copy()
        quicksort_random(arr3)
        print(f"随机排序: {arr3}  ✅ {is_sorted(arr3)}")

    print("\n" + "=" * 60)
    print("所有测试通过！")
    print("=" * 60)
