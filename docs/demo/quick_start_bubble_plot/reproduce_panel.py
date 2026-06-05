import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib import gridspec, patches


PANEL_DIR = Path(__file__).resolve().parent
PNG_PATH = PANEL_DIR / "reproduce_panel.png"
PDF_PATH = PANEL_DIR / "reproduce_panel.pdf"

DPI = 200
FIG_W = 1150 / DPI
FIG_H = 1349 / DPI

COLORS = {
    "FHO": "#2b7bb9",
    "Erythroid": "#f0a341",
    "Lymphoid": "#9082c5",
    "Myeloid": "#5fc0a8",
}

GROUPS = [
    {
        "name": "FHO",
        "labels": [
            "developmental cell growth",
            "establishment or maintenance of cell polarity",
            "cell morphogenesis involved in differentiation",
            "glycerolipid metabolic process",
            "developmental maturation",
            "stem cell development",
            "regulation of granulocyte differentiation",
            "erythrocyte homeostasis",
        ],
        "human_xlim": (2.4, 7.4),
        "mouse_xlim": (1.9, 7.4),
        "human_points": [
            (0, 3.30, 2.05),
            (1, 3.18, 2.00),
            (2, 2.78, 1.85),
        ],
        "mouse_points": [
            (0, 7.15, 2.08),
            (3, 4.55, 2.06),
            (4, 3.08, 1.98),
            (5, 2.65, 1.85),
            (6, 2.55, 1.58),
            (7, 2.35, 1.84),
        ],
    },
    {
        "name": "Erythroid",
        "labels": [
            "negative regulation of cell cycle process",
            "erythrocyte differentiation",
            "developmental cell growth",
            "myeloid progenitor cell differentiation",
        ],
        "human_xlim": (2.8, 7.2),
        "mouse_xlim": (1.8, 7.2),
        "human_points": [
            (0, 6.95, 2.05),
            (1, 3.02, 1.92),
        ],
        "mouse_points": [
            (2, 4.70, 1.95),
            (3, 2.15, 1.10),
        ],
    },
    {
        "name": "Lymphoid",
        "labels": [
            "B cell activation",
            "positive regulation of lymphocyte activation",
            "antigen processing and presentation",
            "somatic diversification of immunoglobulins",
            "immunoglobulin production",
            "T cell receptor signaling pathway",
            "type I interferon production",
            "regulation of lymphocyte activation",
            "developmental cell growth",
            "negative regulation of alpha-beta T cell proliferation",
        ],
        "human_xlim": (2.4, 7.4),
        "mouse_xlim": (1.9, 7.4),
        "human_points": [
            (0, 5.25, 2.05),
            (1, 4.05, 2.02),
            (2, 3.90, 2.05),
            (3, 3.55, 1.88),
            (4, 3.55, 1.95),
            (5, 3.18, 2.00),
            (6, 2.95, 1.88),
            (7, 2.78, 2.08),
        ],
        "mouse_points": [
            (8, 3.30, 1.95),
            (9, 2.65, 1.34),
        ],
    },
    {
        "name": "Myeloid",
        "labels": [
            "neutrophil activation",
            "granulocyte activation",
            "interleukin-12 production",
            "activation of immune response",
            "monocyte differentiation",
            "positive regulation of hemopoiesis",
            "developmental cell growth",
            "myeloid cell differentiation",
        ],
        "human_xlim": (2.2, 7.2),
        "mouse_xlim": (1.9, 7.4),
        "human_points": [
            (0, 5.55, 2.06),
            (1, 5.35, 2.12),
            (2, 5.05, 1.84),
            (3, 4.60, 2.10),
            (4, 3.50, 1.72),
            (5, 3.42, 1.85),
        ],
        "mouse_points": [
            (6, 4.65, 1.98),
            (7, 2.65, 1.98),
        ],
    },
]


def count_to_area(value: float) -> float:
    return 12.5 * (10 ** (value - 1.0))


def style_axis(ax, is_left: bool, xlim: tuple[float, float], labels: list[str], show_xticks: bool) -> None:
    ypos = list(range(len(labels)))
    ax.set_ylim(len(labels) - 0.5, -0.5)
    ax.set_xlim(*xlim)
    ax.set_facecolor("white")
    for spine in ax.spines.values():
        spine.set_linewidth(0.9)
        spine.set_color("#3f3f3f")
    ax.tick_params(axis="both", which="both", direction="out", width=0.9, length=4, color="#3f3f3f")
    ax.tick_params(axis="y", pad=2)
    if show_xticks:
        ticks = [math.ceil(xlim[0]), math.ceil(xlim[0]) + 1, math.ceil(xlim[0]) + 2, math.ceil(xlim[0]) + 3, math.ceil(xlim[0]) + 4]
        ticks = [tick for tick in ticks if tick <= math.floor(xlim[1])]
        ax.set_xticks(ticks)
        ax.set_xticklabels([str(tick) for tick in ticks], fontsize=8)
    else:
        ax.set_xticks([])
    ax.set_yticks(ypos)
    ax.set_yticklabels([])


def add_top_strip(ax, label: str) -> None:
    rect = patches.Rectangle((0.0, 1.0), 1.0, 0.26, transform=ax.transAxes, facecolor="#d8d8d8",
                             edgecolor="#3f3f3f", linewidth=0.9, clip_on=False)
    ax.add_patch(rect)
    ax.text(0.5, 1.13, label, transform=ax.transAxes, ha="center", va="center", fontsize=9, color="#222222")


def add_right_strip(ax, label: str) -> None:
    rect = patches.Rectangle((1.0, 0.0), 0.36, 1.0, transform=ax.transAxes, facecolor="#d8d8d8",
                             edgecolor="#3f3f3f", linewidth=0.9, clip_on=False)
    ax.add_patch(rect)
    ax.text(1.18, 0.5, label, rotation=-90, transform=ax.transAxes, ha="center", va="center", fontsize=9, color="#222222")


def plot_points(ax, points: list[tuple[int, float, float]], color: str) -> None:
    if not points:
        return
    xs = [item[1] for item in points]
    ys = [item[0] for item in points]
    sizes = [count_to_area(item[2]) for item in points]
    ax.scatter(xs, ys, s=sizes, c=color, edgecolors="none", alpha=0.98)


def draw_legend(fig: plt.Figure) -> None:
    ax = fig.add_axes([0.38, 0.055, 0.40, 0.07])
    ax.set_axis_off()
    ax.set_xlim(0, 10.8)
    ax.set_ylim(0, 1)
    ax.text(0.0, 0.5, r"$\log_{10}(\mathrm{count})$", fontsize=8.2, ha="left", va="center")
    values = [1.0, 1.4, 1.8, 2.2]
    x_positions = [4.7, 6.1, 7.7, 9.5]
    for xpos, value in zip(x_positions, values):
        ax.scatter([xpos], [0.5], s=count_to_area(value), c="black", edgecolors="none")
        ax.text(xpos + 0.42, 0.46, f"{value:.1f}", fontsize=8, ha="left", va="center")


def build_figure() -> plt.Figure:
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "axes.linewidth": 0.9,
        "xtick.major.width": 0.9,
        "ytick.major.width": 0.9,
    })
    fig = plt.figure(figsize=(FIG_W, FIG_H), dpi=DPI, facecolor="white")
    gs = gridspec.GridSpec(
        nrows=4,
        ncols=2,
        figure=fig,
        left=0.57,
        right=0.915,
        top=0.945,
        bottom=0.19,
        hspace=0.10,
        wspace=0.11,
        height_ratios=[8, 4, 10, 8],
    )

    for row_idx, group in enumerate(GROUPS):
        ax_left = fig.add_subplot(gs[row_idx, 0])
        ax_right = fig.add_subplot(gs[row_idx, 1], sharey=ax_left)
        style_axis(
            ax_left,
            is_left=True,
            xlim=group["human_xlim"],
            labels=group["labels"],
            show_xticks=(row_idx == len(GROUPS) - 1),
        )
        style_axis(
            ax_right,
            is_left=False,
            xlim=group["mouse_xlim"],
            labels=group["labels"],
            show_xticks=(row_idx == len(GROUPS) - 1),
        )
        plot_points(ax_left, group["human_points"], COLORS[group["name"]])
        plot_points(ax_right, group["mouse_points"], COLORS[group["name"]])
        if row_idx == 0:
            add_top_strip(ax_left, "Human")
            add_top_strip(ax_right, "Mouse")
        add_right_strip(ax_right, group["name"])

        pos = ax_left.get_position()
        label_x = 0.535
        n_labels = len(group["labels"])
        for label_idx, label in enumerate(group["labels"]):
            frac_y = 1.0 - (label_idx + 0.5) / n_labels
            fig.text(label_x, pos.y0 + pos.height * frac_y, label, ha="right", va="center", fontsize=7.2, color="#111111")

    fig.text(0.735, 0.135, r"$-\log_{10}(\mathrm{p.\!value})$", ha="center", va="center", fontsize=9.6)
    draw_legend(fig)
    return fig


def main() -> int:
    PANEL_DIR.mkdir(parents=True, exist_ok=True)
    fig = build_figure()
    fig.savefig(PNG_PATH, dpi=DPI)
    fig.savefig(PDF_PATH, dpi=DPI)
    plt.close(fig)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
