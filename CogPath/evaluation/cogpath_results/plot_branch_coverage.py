#!/usr/bin/env python3
"""
分支覆盖率对比图表绘制脚本
====================================

使用方法:
    python3 plot_branch_coverage.py

输出:
    - branch_coverage_comparison.svg (矢量图)
    - branch_coverage_comparison.png (PNG图片)
"""

import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

# 设置顶级会议常用字体
plt.rcParams['font.family'] = 'serif'
plt.rcParams['font.serif'] = ['Times New Roman', 'DejaVu Serif', 'Bitstream Vera Serif']
plt.rcParams['font.size'] = 14
plt.rcParams['axes.labelsize'] = 16
plt.rcParams['axes.titlesize'] = 18
plt.rcParams['xtick.labelsize'] = 14
plt.rcParams['ytick.labelsize'] = 14
plt.rcParams['legend.fontsize'] = 16
plt.rcParams['font.weight'] = 'normal'

# ============================================================
# 配置区域 - 请在此修改配置
# ============================================================

# 输入文件路径
INPUT_CSV = '/mnt/data1/ljh/code/Panta/evaluation/cogpath_results/branch_coverage_4configs_8iter.csv'

# 输出文件目录
OUTPUT_DIR = '/mnt/data1/ljh/code/Panta/evaluation/figures/'

# 配置名称映射 (原名 -> 显示名)
CONFIG_NAMES = {
    'cs_bs': 'CogPath (Ours)',
    'bs': 'w/o BS',
    'cs': 'w/o CS',
    'baseline': 'Base (w/o CS+BS)'
}

# 颜色配置
COLORS = {
    'CogPath (Ours)': '#2ca02c',      # 绿色
    'w/o BS': '#ff7f0e',              # 橙色
    'w/o CS': '#d62728',              # 红色
    'Base (w/o CS+BS)': '#1f77b4'     # 蓝色
}

# 标记配置 (圆形, 菱形, 方块, 三角形)
MARKERS = {
    'CogPath (Ours)': 'o',    # 圆形
    'w/o BS': 'D',            # 菱形
    'w/o CS': 's',            # 方块
    'Base (w/o CS+BS)': '^'  # 三角形
}

# 图表标题和标签
FIGURE_TITLE = 'Branch Coverage Comparison across Iterations'
X_LABEL = 'Iteration'
Y_LABEL = 'Branch Coverage (%)'

# 图表大小
FIG_SIZE = (12, 8)

# Y轴范围
Y_MIN = 10
Y_MAX = 50

# ============================================================
# 主程序 - 通常不需要修改
# ============================================================

def main():
    print("=" * 60)
    print("分支覆盖率对比图表生成")
    print("=" * 60)

    # 加载数据
    print(f"\n加载数据: {INPUT_CSV}")
    df = pd.read_csv(INPUT_CSV)
    print(f"数据行数: {len(df)}")

    # 创建图表
    fig, ax = plt.subplots(figsize=FIG_SIZE)

    # 绘制每种配置
    for config_key, display_name in CONFIG_NAMES.items():
        iterations = []
        averages = []

        for i in range(8):
            col = f'{config_key}_iter{i}'
            if col in df.columns:
                avg = df[col].mean()
                if not pd.isna(avg):
                    iterations.append(i)
                    averages.append(avg)

        if iterations:
            ax.plot(iterations, averages,
                   label=display_name,
                   color=COLORS.get(display_name),
                   marker=MARKERS.get(display_name, 'o'),
                   linewidth=2.5,
                   markersize=10)

    # 设置标题和标签
    ax.set_title(FIGURE_TITLE, fontsize=20, fontweight='bold', pad=20)
    ax.set_xlabel(X_LABEL, fontsize=18)
    ax.set_ylabel(Y_LABEL, fontsize=18)

    # 设置坐标轴
    ax.set_xticks(range(8))
    ax.set_xticklabels([f'#{i}' for i in range(8)], fontsize=16)
    ax.set_ylim(Y_MIN, Y_MAX)

    # 添加网格
    ax.grid(True, linestyle='--', alpha=0.7)

    # 添加图例
    ax.legend(loc='lower right', fontsize=16)

    # 调整布局
    plt.tight_layout()

    # 保存矢量图 (SVG)
    svg_path = OUTPUT_DIR + 'branch_coverage_comparison.svg'
    plt.savefig(svg_path, format='svg', dpi=300, bbox_inches='tight')
    print(f"\n已保存矢量图: {svg_path}")

    # 保存PNG图片
    png_path = OUTPUT_DIR + 'branch_coverage_comparison.png'
    plt.savefig(png_path, format='png', dpi=300, bbox_inches='tight')
    print(f"已保存PNG图: {png_path}")

    # 保存PDF图片
    pdf_path = OUTPUT_DIR + 'branch_coverage_comparison.pdf'
    plt.savefig(pdf_path, format='pdf', bbox_inches='tight')
    print(f"已保存PDF图: {pdf_path}")

    plt.close()

    # 输出统计摘要
    print("\n" + "=" * 60)
    print("统计摘要 (平均分支覆盖率)")
    print("=" * 60)

    for config_key, display_name in CONFIG_NAMES.items():
        print(f"\n【{display_name}】")
        for i in range(8):
            col = f'{config_key}_iter{i}'
            if col in df.columns:
                avg = df[col].mean()
                if not pd.isna(avg):
                    print(f"  iter {i}: {avg:.2f}%")

    print("\n完成!")

if __name__ == '__main__':
    main()
