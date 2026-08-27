"""Render the static infographics used by the README and ReadTheDocs landing page.

Produces three PNGs in ``docs/_static/``:

- ``architecture.png``: data flow from ServiceNow tables through snowloader to
  framework adapters and downstream consumers.
- ``performance.png``: relative throughput across the three pagination paths.
- ``decision.png``: a small decision tree for picking which API to use.

Run this script whenever the diagrams change; the resulting PNGs are committed
so PyPI and ReadTheDocs render them without needing matplotlib at build time.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "_static"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Cool-blue palette anchored by the existing logo
COLOR_PRIMARY = "#1a73e8"
COLOR_ACCENT = "#4fc3f7"
COLOR_DEEP = "#0b3d91"
COLOR_TEXT = "#0f172a"
COLOR_MUTED = "#475569"
COLOR_SUCCESS = "#10b981"
COLOR_BG = "#f8fafc"
COLOR_CARD = "#ffffff"
COLOR_BORDER = "#cbd5e1"

FONT_FAMILY = "DejaVu Sans"


def style_axes(ax: plt.Axes) -> None:
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")


def round_box(
    ax: plt.Axes,
    x: float,
    y: float,
    w: float,
    h: float,
    text: str,
    fill: str,
    edge: str = COLOR_BORDER,
    text_color: str = COLOR_TEXT,
    fontsize: int = 11,
    weight: str = "normal",
) -> None:
    box = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.02,rounding_size=1.2",
        linewidth=1.2,
        edgecolor=edge,
        facecolor=fill,
    )
    ax.add_patch(box)
    ax.text(
        x + w / 2,
        y + h / 2,
        text,
        ha="center",
        va="center",
        fontsize=fontsize,
        color=text_color,
        family=FONT_FAMILY,
        weight=weight,
    )


def arrow(ax: plt.Axes, x1: float, y1: float, x2: float, y2: float) -> None:
    ax.add_patch(
        FancyArrowPatch(
            (x1, y1),
            (x2, y2),
            arrowstyle="-|>",
            mutation_scale=14,
            linewidth=1.6,
            color=COLOR_DEEP,
            shrinkA=2,
            shrinkB=2,
        )
    )


def build_architecture() -> None:
    fig, ax = plt.subplots(figsize=(14, 7), dpi=140)
    fig.patch.set_facecolor(COLOR_BG)
    ax.set_facecolor(COLOR_BG)
    style_axes(ax)

    ax.text(
        50,
        95,
        "snowloader data flow",
        ha="center",
        va="center",
        fontsize=16,
        weight="bold",
        color=COLOR_TEXT,
        family=FONT_FAMILY,
    )

    # Column headers (drawn after boxes won't overlap because top is reserved)
    ax.text(13, 88, "ServiceNow", ha="center", va="center", fontsize=11, color=COLOR_MUTED, family=FONT_FAMILY, weight="bold")
    ax.text(45, 88, "snowloader", ha="center", va="center", fontsize=11, color=COLOR_MUTED, family=FONT_FAMILY, weight="bold")
    ax.text(75, 88, "Adapters", ha="center", va="center", fontsize=11, color=COLOR_MUTED, family=FONT_FAMILY, weight="bold")
    ax.text(92, 88, "Downstream", ha="center", va="center", fontsize=11, color=COLOR_MUTED, family=FONT_FAMILY, weight="bold")

    # Column 1: ServiceNow tables
    table_labels = [
        "incident",
        "kb_knowledge",
        "cmdb_ci",
        "cmdb_rel_ci",
        "change_request",
        "problem",
        "sc_cat_item",
        "sys_attachment",
        "any other table",
    ]
    col1_x = 2
    col1_w = 22
    table_h = 6.0
    table_gap = 1.3
    col1_top = 80
    for i, label in enumerate(table_labels):
        y = col1_top - i * (table_h + table_gap)
        round_box(ax, col1_x, y, col1_w, table_h, label, COLOR_CARD, fontsize=10)

    # Column 2: snowloader card
    col2_x = 32
    col2_w = 26
    col2_y = 12
    col2_h = 70
    round_box(
        ax,
        col2_x,
        col2_y,
        col2_w,
        col2_h,
        "",
        COLOR_PRIMARY,
        edge=COLOR_DEEP,
        text_color=COLOR_CARD,
    )
    ax.text(
        col2_x + col2_w / 2,
        col2_y + col2_h - 7,
        "snowloader",
        ha="center",
        va="center",
        fontsize=15,
        weight="bold",
        color=COLOR_CARD,
        family=FONT_FAMILY,
    )
    inner_lines = [
        "SnowConnection",
        "AsyncSnowConnection",
        "concurrent_get_records",
        "verify=True",
        "9 loaders",
        "SnowDocument",
    ]
    line_top = col2_y + col2_h - 17
    line_step = 7.5
    for i, t in enumerate(inner_lines):
        ax.text(
            col2_x + col2_w / 2,
            line_top - i * line_step,
            t,
            ha="center",
            va="center",
            fontsize=10.5,
            color=COLOR_CARD,
            family=FONT_FAMILY,
        )

    # Column 3: adapters (further right with bigger gap from snowloader card)
    col3_x = 64
    col3_w = 22
    adapters = [
        ("LangChain adapter", 65),
        ("LlamaIndex adapter", 50),
        ("Native dict / JSONL", 35),
    ]
    for label, y in adapters:
        round_box(ax, col3_x, y, col3_w, 8, label, COLOR_CARD, fontsize=10.5)

    # Column 4: downstream consumers (placed further right, no overlap)
    col4_x = 88
    col4_w = 11
    downstream = [
        ("Vector\nstore", 65),
        ("RAG\nagent", 50),
        ("ETL\npipeline", 35),
    ]
    for label, y in downstream:
        round_box(ax, col4_x, y, col4_w, 8, label, COLOR_ACCENT, fontsize=10)

    # Arrows: tables -> snowloader
    snowloader_left_y = 50
    for i in range(len(table_labels)):
        y = col1_top + table_h / 2 - i * (table_h + table_gap)
        arrow(ax, col1_x + col1_w + 0.4, y, col2_x - 0.4, snowloader_left_y)

    # Arrows: snowloader -> adapters (from right edge of snowloader card)
    snowloader_right_x = col2_x + col2_w
    for _, y in adapters:
        arrow(ax, snowloader_right_x + 0.4, snowloader_left_y, col3_x - 0.4, y + 4)

    # Arrows: adapters -> downstream
    for (_, y_src), (_, y_dst) in zip(adapters, downstream):
        arrow(ax, col3_x + col3_w + 0.4, y_src + 4, col4_x - 0.4, y_dst + 4)

    fig.tight_layout(pad=0.6)
    fig.savefig(OUT_DIR / "architecture.png", facecolor=fig.get_facecolor())
    plt.close(fig)


def build_performance() -> None:
    """Threaded worker scaling, from scripts/benchmark_v030.py on a live instance."""
    fig, ax = plt.subplots(figsize=(10, 4.6), dpi=140)
    fig.patch.set_facecolor(COLOR_BG)
    ax.set_facecolor(COLOR_BG)

    labels = ["sequential", "4 workers", "8 workers", "16 workers", "32 workers"]
    seconds = [46.4, 14.6, 8.2, 6.4, 8.1]
    speedup = [46.4 / s for s in seconds]
    colors = [COLOR_MUTED, COLOR_ACCENT, COLOR_ACCENT, COLOR_PRIMARY, COLOR_ACCENT]

    bars = ax.bar(labels, seconds, color=colors, edgecolor=COLOR_BORDER, linewidth=0.8, width=0.62)
    for bar, sec, mult in zip(bars, seconds, speedup, strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 1.2,
            f"{sec}s\n{mult:.1f}x",
            ha="center",
            va="bottom",
            fontsize=10.5,
            color=COLOR_TEXT,
            family=FONT_FAMILY,
            weight="bold",
        )

    ax.annotate(
        "peak, and the default",
        xy=(3, 6.4),
        xytext=(2.55, 30),
        ha="center",
        fontsize=10,
        color=COLOR_DEEP,
        family=FONT_FAMILY,
        weight="bold",
        arrowprops={"arrowstyle": "->", "color": COLOR_DEEP, "linewidth": 1.4},
    )

    ax.set_title(
        "Threaded sweep of 2,919 records, measured on a developer instance",
        fontsize=13,
        color=COLOR_TEXT,
        family=FONT_FAMILY,
        weight="bold",
        pad=14,
    )
    ax.set_ylabel("seconds, lower is better", color=COLOR_MUTED, family=FONT_FAMILY, fontsize=10)
    ax.tick_params(colors=COLOR_MUTED, labelsize=10.5)
    for spine_name in ("top", "right"):
        ax.spines[spine_name].set_visible(False)
    for spine_name in ("left", "bottom"):
        ax.spines[spine_name].set_color(COLOR_BORDER)
    ax.set_ylim(0, 56)
    ax.grid(axis="y", color=COLOR_BORDER, linestyle="--", alpha=0.4)

    ax.text(
        0.99,
        -0.20,
        "Throughput turns over after 16 workers. Reproduce with scripts/benchmark_v030.py.",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=9,
        color=COLOR_MUTED,
        family=FONT_FAMILY,
        style="italic",
    )

    fig.tight_layout(pad=1.2)
    fig.savefig(OUT_DIR / "performance.png", facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)


def build_pagination() -> None:
    """Why offset paging over a non-unique sort column loses rows, and the fix."""
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.2), dpi=140)
    fig.patch.set_facecolor(COLOR_BG)

    # Eight rows that all share one sys_created_on value, paged 4 at a time.
    # Left: the server is free to reorder inside the tie, so page 2 re-serves
    # rows page 1 already gave us and never serves C and D.
    before_page1 = ["A", "B", "C", "D"]
    before_page2 = ["A", "B", "E", "F"]
    after_page1 = ["A", "B", "C", "D"]
    after_page2 = ["E", "F", "G", "H"]

    panels = [
        (axes[0], "Before 0.3.0", "ORDERBYsys_created_on", before_page1, before_page2,
         {"A", "B"}, "G and H never arrive. A and B arrive twice."),
        (axes[1], "0.3.0", "ORDERBYsys_created_on^ORDERBYsys_id", after_page1, after_page2,
         set(), "Every row exactly once."),
    ]

    for ax, title, query, page1, page2, dup, caption in panels:
        ax.set_facecolor(COLOR_BG)
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 10)
        ax.axis("off")

        ax.text(5, 9.6, title, ha="center", va="center", fontsize=14,
                color=COLOR_TEXT, family=FONT_FAMILY, weight="bold")
        ax.text(5, 8.85, query, ha="center", va="center", fontsize=9.5,
                color=COLOR_MUTED, family="DejaVu Sans Mono")

        for row_i, (label, rows) in enumerate((("page 1", page1), ("page 2", page2))):
            y = 7.2 - row_i * 3.1
            ax.text(0.4, y + 0.92, label, ha="left", va="center", fontsize=10.5,
                    color=COLOR_MUTED, family=FONT_FAMILY, weight="bold")
            for col_i, cell in enumerate(rows):
                x = 0.4 + col_i * 2.25
                is_dup = row_i == 1 and cell in dup
                face = "#fde2e1" if is_dup else COLOR_CARD
                edge = "#d93025" if is_dup else COLOR_BORDER
                ax.add_patch(FancyBboxPatch(
                    (x, y - 0.55), 2.0, 1.05,
                    boxstyle="round,pad=0.02,rounding_size=0.12",
                    facecolor=face, edgecolor=edge, linewidth=1.6 if is_dup else 1.0))
                ax.text(x + 1.0, y - 0.02, cell, ha="center", va="center", fontsize=13,
                        color="#d93025" if is_dup else COLOR_TEXT,
                        family=FONT_FAMILY, weight="bold")
                if is_dup:
                    ax.text(x + 1.0, y - 0.95, "duplicate", ha="center", va="center",
                            fontsize=8.5, color="#d93025", family=FONT_FAMILY, weight="bold")

        ok = not dup
        ax.add_patch(FancyBboxPatch(
            (0.4, 0.55), 9.0, 1.5,
            boxstyle="round,pad=0.02,rounding_size=0.14",
            facecolor="#e6f4ea" if ok else "#fdeceb",
            edgecolor=COLOR_SUCCESS if ok else "#d93025", linewidth=1.4))
        ax.text(4.9, 1.55, caption, ha="center", va="center", fontsize=10.5,
                color=COLOR_SUCCESS if ok else "#d93025",
                family=FONT_FAMILY, weight="bold")
        ax.text(4.9, 0.98,
                "returned 2919, distinct 2919" if ok else
                "returned 2919, distinct 2915, and the count still reconciles",
                ha="center", va="center", fontsize=9.5, color=COLOR_MUTED,
                family="DejaVu Sans Mono")

    fig.suptitle(
        "Offset pagination is only safe over a unique sort key",
        fontsize=15, color=COLOR_TEXT, family=FONT_FAMILY, weight="bold", y=0.99)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(OUT_DIR / "pagination.png", facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)


def build_references() -> None:
    """What a loader put in metadata before 0.3.0, and what it puts there now."""
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.4), dpi=150)
    fig.patch.set_facecolor(COLOR_BG)

    before = [
        ("sys_id", "\"{'display_value': '02a7...',", "#d93025"),
        ("", " 'value': '02a7...'}\"", "#d93025"),
        ("assigned_to", "'David Loo'", COLOR_TEXT),
        ("assignment_group", "''", COLOR_MUTED),
        ("cmdb_ci", "'b297b098...'", "#d93025"),
        ("caller_id", "absent", "#d93025"),
        ("opened_by", "absent", "#d93025"),
        ("priority", "'5 - Planning'", COLOR_TEXT),
    ]
    after = [
        ("sys_id", "'02a73898...'", COLOR_SUCCESS),
        ("assigned_to", "'David Loo'", COLOR_TEXT),
        ("assigned_to_sys_id", "'6816f79c...'", COLOR_SUCCESS),
        ("assignment_group", "'Service Desk'", COLOR_TEXT),
        ("assignment_group_sys_id", "'d625dcce...'", COLOR_SUCCESS),
        ("cmdb_ci", "'PROD-DB-01'", COLOR_TEXT),
        ("cmdb_ci_sys_id", "'b297b098...'", COLOR_SUCCESS),
        ("caller_id", "'survey user'", COLOR_TEXT),
        ("caller_id_sys_id", "'005d500b...'", COLOR_SUCCESS),
        ("priority", "'5 - Planning'", COLOR_TEXT),
        ("priority_value", "'5'", COLOR_SUCCESS),
    ]

    panels = [
        (axes[0], "Before 0.3.0", before,
         "No identifier anywhere. Nothing joins to anything.", False),
        (axes[1], "0.3.0", after,
         "Every reference joinable. Primary key is a plain string.", True),
    ]

    for ax, title, rows, caption, ok in panels:
        ax.set_facecolor(COLOR_BG)
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 13.4)
        ax.axis("off")

        ax.text(5, 12.9, title, ha="center", va="center", fontsize=14,
                color=COLOR_TEXT, family=FONT_FAMILY, weight="bold")
        ax.text(5, 12.15, "doc.metadata", ha="center", va="center", fontsize=9.5,
                color=COLOR_MUTED, family="DejaVu Sans Mono")

        top = 11.3
        step = 0.86
        for i, (key, value, colour) in enumerate(rows):
            y = top - i * step
            if key:
                ax.text(0.35, y, key, ha="left", va="center", fontsize=10,
                        color=COLOR_TEXT, family="DejaVu Sans Mono")
            ax.text(5.15, y, value, ha="left", va="center", fontsize=10,
                    color=colour, family="DejaVu Sans Mono",
                    weight="bold" if colour in (COLOR_SUCCESS, "#d93025") else "normal")

        ax.add_patch(FancyBboxPatch(
            (0.25, 0.35), 9.4, 1.25,
            boxstyle="round,pad=0.02,rounding_size=0.14",
            facecolor="#e6f4ea" if ok else "#fdeceb",
            edgecolor=COLOR_SUCCESS if ok else "#d93025", linewidth=1.4))
        ax.text(4.95, 0.97, caption, ha="center", va="center", fontsize=9.5,
                color=COLOR_SUCCESS if ok else "#d93025",
                family=FONT_FAMILY, weight="bold")

    fig.suptitle(
        "Reference fields now carry both halves",
        fontsize=15, color=COLOR_TEXT, family=FONT_FAMILY, weight="bold", y=0.99)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(OUT_DIR / "references.png", facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)


def build_decision() -> None:
    fig, ax = plt.subplots(figsize=(10, 5.4), dpi=140)
    fig.patch.set_facecolor(COLOR_BG)
    ax.set_facecolor(COLOR_BG)
    style_axes(ax)

    ax.text(
        50,
        95,
        "Pick the right API in 30 seconds",
        ha="center",
        va="center",
        fontsize=14,
        weight="bold",
        color=COLOR_TEXT,
        family=FONT_FAMILY,
    )

    # Top question
    round_box(ax, 30, 78, 40, 9, "Are you in an asyncio app?", COLOR_CARD, fontsize=12, weight="bold")

    # Yes branch (left)
    round_box(ax, 4, 60, 28, 8, "AsyncSnowConnection", COLOR_PRIMARY, edge=COLOR_DEEP, text_color=COLOR_CARD, weight="bold")
    round_box(ax, 4, 50, 28, 7, "aget_records / aload", COLOR_CARD, fontsize=10)
    arrow(ax, 38, 78, 18, 68)
    ax.text(26, 74, "yes", fontsize=10, color=COLOR_DEEP, family=FONT_FAMILY, weight="bold")

    # No branch (right) -> "more than a few thousand records?"
    round_box(ax, 60, 60, 36, 8, "More than a few thousand records?", COLOR_CARD, fontsize=11, weight="bold")
    arrow(ax, 62, 78, 78, 68)
    ax.text(72, 74, "no", fontsize=10, color=COLOR_DEEP, family=FONT_FAMILY, weight="bold")

    # Right yes -> threaded
    round_box(ax, 60, 42, 36, 8, "concurrent_get_records / concurrent_load", COLOR_PRIMARY, edge=COLOR_DEEP, text_color=COLOR_CARD, fontsize=10.5, weight="bold")
    arrow(ax, 70, 60, 70, 50)
    ax.text(72, 55, "yes", fontsize=10, color=COLOR_DEEP, family=FONT_FAMILY, weight="bold")

    # Right no -> sequential
    round_box(ax, 60, 24, 36, 8, "get_records / load", COLOR_CARD, fontsize=11, weight="bold")
    arrow(ax, 90, 60, 90, 32)
    ax.text(92, 55, "no", fontsize=10, color=COLOR_DEEP, family=FONT_FAMILY, weight="bold")

    # Footnote
    ax.text(
        50,
        8,
        "Threaded path keeps each worker on its own requests.Session for stable behavior under load.",
        ha="center",
        va="center",
        fontsize=9.5,
        color=COLOR_MUTED,
        family=FONT_FAMILY,
        style="italic",
    )

    fig.tight_layout(pad=0.6)
    fig.savefig(OUT_DIR / "decision.png", facecolor=fig.get_facecolor())
    plt.close(fig)


def main() -> None:
    build_architecture()
    build_performance()
    build_pagination()
    build_references()
    build_decision()
    print("Wrote:")
    for name in ("architecture.png", "performance.png", "decision.png"):
        path = OUT_DIR / name
        size_kb = path.stat().st_size / 1024
        print(f"  {path.relative_to(OUT_DIR.parent.parent)} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
