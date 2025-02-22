from collections import defaultdict
from datetime import datetime, timedelta
from enum import IntFlag
from xml.dom import DOMException

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import unidecode
from matplotlib.patches import Rectangle, Circle
from matplotlib.ticker import PercentFormatter

from poc.VanetTraceLoader import get_grid
from poc.render import VEC_STATION_COLORS
from poc.scenarios import CRETEIL_4_RSU_FULL_CAPA_CONFIG, CRETEIL_9_RSU_FULL_CAPA_CONFIG, \
    CRETEIL_3_FAIL_RSU_FULL_CAPA_CONFIG
from poc.base import RsuConfig


def plot_distribution(models, means, stds, title, ylabel):
    plt.figure(figsize=(10, 5))
    colors = plt.get_cmap('tab10', len(models))
    for i, (model, mean, std) in enumerate(zip(models, means, stds)):
        x = np.linspace(max(0, mean - 3 * std), min(1, mean + 3 * std, 100))
        y = (1 / (std * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((x - mean) / std) ** 2)
        plt.plot(x, y, label=model, color=colors(i))
    # plt.title(f'Distribution of {title}')
    plt.xlabel(f'{ylabel} Value')
    plt.ylabel('Density')
    plt.legend(title="Models")
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.tight_layout()
    plt.show()


def custom_sort_key(model_name):
    if '-Oracle' in model_name:
        return 0, model_name
    return 1, model_name


def visualize_results(configs, experiment_title, plot_ho=True):
    configs = [(filename,
                pd.read_csv(f"../results/{filename}.csv").sort_values(by='Model', key=lambda x: x.map(custom_sort_key)),
                res_title)
               for filename, res_title in configs]

    if plot_ho:
        for filename, df, res_title in configs:
            plot_ho_count(filename, df, res_title)

    plot_metric(experiment_title, configs, 'GiniMean', 'Average Load Distribution Inequality (Gini Coefficient)',
                'Gini Coefficient',
                percentage=False, is_gini=True)
    plot_metric(experiment_title, configs, 'AvgQoSMean', 'Overall Network Performance (Average QoS)', 'Average QoS (%)',
                percentage=True)
    plot_metric(experiment_title, configs, 'MinQoSMean', 'Worst-Case Service Quality (Minimum QoS)', 'Minimum QoS (%)',
                percentage=True)


def plot_metric(experiment, configs, metric_col, title, ylabel, percentage=False, is_gini=False):
    plt.figure(figsize=(10, 5))

    colors = plt.get_cmap('tab10', 10)  # Get a colormap with at least 10 colors
    baseline_values = {}
    for i, (filename, df, res_title) in enumerate(configs):
        models = df['Model']
        metric_mean = df[metric_col]

        first_group = models[models.str.startswith('ARHC')]
        first_group_metric = metric_mean[:len(first_group)]

        last_group = models[len(first_group):]
        last_group_metric = metric_mean[len(first_group):]

        plt.plot(first_group, first_group_metric, label=f"ARHC - {res_title}", marker='o', color=colors(i))

        if is_gini:
            part_title = res_title.split(' ')[0]
            baseline_values[part_title] = (last_group, last_group_metric, f"Baseline - {part_title}")
        else:
            plt.scatter(last_group, last_group_metric, label=f"Baseline - {res_title}", marker='s',
                        color=colors(i))

    if is_gini:
        for j, (baseline_group, baseline_metric, baseline_title) in enumerate(baseline_values.values()):
            plt.scatter(baseline_group, baseline_metric, label=baseline_title, marker='s',
                        color=colors(len(configs) + j))

    legend_loc = "upper left" if is_gini else "lower left"

    # plt.title(f'{experiment}: {title}')
    plt.xlabel('Handover Coordination Strategy')
    plt.ylabel(ylabel)
    if percentage:
        plt.gca().yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{x:.0%}'))
    plt.legend(title="Strategies & Configurations", loc=legend_loc)
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()

    filename = f'results_{unidecode.unidecode(experiment).strip().lower().replace(" ", "_")}_{metric_col.lower().replace(" ", "_")}.png'
    plt.savefig(filename, format="png", dpi=200)
    plt.show()


def plot_ho_count(filename, df, title):
    models = df['Model']
    ho_range = df['HO_Range']
    ho_load_balancing = df['HO_LB']
    ho_overload = df['HO_Overload']
    successful = df['HO_Total']
    failed = df['HO_Failed']

    x = range(len(models))
    width = 0.35

    fig, ax = plt.subplots(figsize=(6, 4))

    ax.bar(x, ho_range, width, label='Range HO', color='tab:blue')
    ax.bar(x, ho_load_balancing, width, bottom=ho_range, label='Load Balancing HO', color='tab:orange')
    ax.bar(x, ho_overload, width, bottom=ho_range + ho_load_balancing, label='Overload HO', color='tab:green')

    ax.bar([p + width for p in x], failed, width, label='Failed HO', color='tab:red')

    legend_loc = "lower right"
    # If max of last 3 bars is more than double of first, put the legend to upper left
    if np.max(successful[-3:]) > 2 * successful[0]:
        legend_loc = "upper left"

    # ax.set_title(f'{title}: Successful and Failed Handovers')
    ax.set_xlabel('Handover Coordination Strategy')
    ax.set_ylabel('Number of Handovers')
    ax.set_xticks([p + width / 2 for p in x])
    ax.set_xticklabels(models, rotation=45, ha='right')
    ax.legend(title="Handover Type", loc=legend_loc)
    ax.grid(True)

    plt.tight_layout()
    plt.savefig(f'{unidecode.unidecode(filename)}_handovers.png', format="png", dpi=200)
    plt.show()


def plot_metrics_over_time(scenario, rsu_config, strategy, morning=True):
    filename = f"../results/runs/result_{scenario}_{rsu_config}_{strategy}_model_vars.csv"
    df = pd.read_csv(filename)
    df = df.iloc[1:-1].reset_index(drop=True)  # Remove first and last row

    file_prefix = f"{scenario}_{rsu_config}_{strategy}"

    colors = plt.get_cmap('tab20', 20)

    qos_colors = {
        'MinQoS': colors(0),
        'AvgQoS': colors(2),
        'MinQoS_RangeBased': colors(1),
        'MinQoS_LoadBased': colors(0),
        'AvgQoS_RangeBased': colors(3),
        'AvgQoS_LoadBased': colors(2),
    }

    def rolling(col, window=30):
        return col.rolling(window=window, min_periods=1).mean()

    # Time setup
    start_time = datetime.strptime("07:15:00" if morning else "17:15:00", "%H:%M:%S")
    experiment_start = start_time
    experiment_end = experiment_start + timedelta(seconds=len(df) - 1)
    times = [start_time + timedelta(seconds=i) for i in df.index]

    def setup_time_axis(ax):
        ax.xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter('%H:%M'))
        ax.xaxis.set_major_locator(plt.matplotlib.dates.MinuteLocator(byminute=[15, 30, 45, 0]))
        plt.setp(ax.get_xticklabels(), rotation=0, ha='center')

    # 1. Vehicle count over time
    plt.figure(figsize=(8, 5))
    plt.plot(times, rolling(df['VehicleCount'], 10), label='Vehicle Count', color='tab:blue')
    # plt.title('Number of Vehicles Over Time - 10s Smoothing')
    plt.ylabel('Number of Vehicles')
    plt.grid(True)
    setup_time_axis(plt.gca())
    plt.tight_layout()
    plt.savefig(f"{file_prefix}_vehicle_count.png", format="png", dpi=200)
    plt.show()
    plt.close()

    qos_roll_window = 10

    # 2. Min QoS and Avg QoS over time
    plt.figure(figsize=(8, 5))
    plt.plot(times, rolling(df['MinQoS'], qos_roll_window), label='Minimum QoS', color=qos_colors['MinQoS'])
    plt.plot(times, rolling(df['AvgQoS'], qos_roll_window), label='Average QoS', color=qos_colors['AvgQoS'])
    # plt.title(f'Minimum and Average QoS Over Time - {qos_roll_window}s Smoothing')
    # plt.xlabel('Time')
    plt.ylabel('QoS (%)')
    plt.gca().yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    plt.legend()
    plt.grid(True)
    setup_time_axis(plt.gca())
    plt.tight_layout()
    plt.savefig(f"{file_prefix}_min_avg_qos.png", format="png", dpi=200)
    plt.show()
    plt.close()

    # 3. Min Range QoS and Min Load QoS over time
    plt.figure(figsize=(8, 5))
    plt.plot(times, rolling(df['MinQoS_LoadBased'], qos_roll_window), label='Load-based Minimum QoS',
             color=qos_colors['MinQoS_LoadBased'])
    plt.plot(times, rolling(df['AvgQoS_LoadBased'], qos_roll_window), label='Load-based Average QoS',
             color=qos_colors['AvgQoS_LoadBased'])
    plt.plot(times, rolling(df['MinQoS_RangeBased'], qos_roll_window), label='Distance-based Minimum QoS',
             color=qos_colors['MinQoS_RangeBased'])
    plt.plot(times, rolling(df['AvgQoS_RangeBased'], qos_roll_window), label='Distance-based Average QoS',
             color=qos_colors['AvgQoS_RangeBased'])

    # plt.title('Worst-Case Service Quality (Min Range and Load QoS)')
    # plt.title(f'QoS Over Time - Load-based vs Distance-based - {qos_roll_window}s Smoothing')
    # plt.xlabel('Time')
    plt.ylabel('QoS (%)')
    plt.gca().yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    plt.legend()
    plt.grid(True)
    setup_time_axis(plt.gca())
    plt.tight_layout()
    plt.savefig(f"{file_prefix}_min_range_load_qos.png", format="png", dpi=200)
    plt.show()
    plt.close()

    # 4. Avg Range QoS and Avg Load QoS over time
    # plt.figure(figsize=(8, 5))
    # plt.plot(times, df['AvgQoS_RangeBased'], label='Avg Range QoS', color=qos_colors['AvgQoS_RangeBased'])
    # plt.plot(times, df['AvgQoS_LoadBased'], label='Avg Load QoS', color=qos_colors['AvgQoS_LoadBased'])
    # plt.title('Network Performance (Avg Range and Load QoS)')
    # plt.title('Average QoS Over Time - Distance-based vs Load-based')
    # # plt.xlabel('Time')
    # plt.ylabel('QoS (%)')
    # plt.gca().yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    # plt.legend()
    # plt.grid(True)
    # setup_time_axis(plt.gca())
    # plt.tight_layout()
    # plt.savefig(f"{file_prefix}_avg_range_load_qos.png", format="png", dpi=200)
    # plt.show()
    # plt.close()

    # 5. Gini Load over time
    smoothing_window = 30
    smoothed_gini = rolling(df['GiniLoad'], 30)

    plt.figure(figsize=(8, 5))
    plt.plot(times, smoothed_gini, label='Gini Load', color='tab:cyan')
    # plt.title('Load Distribution Inequality (Gini Coefficient) - 30s Smoothing')
    # plt.xlabel('Time')
    plt.ylabel('Gini Coefficient')
    plt.grid(True)
    setup_time_axis(plt.gca())
    plt.tight_layout()
    plt.savefig(f"{file_prefix}_gini_load.png", format="png", dpi=200)
    plt.show()
    plt.close()

    # 6. Successful HO and Failed HO over time using 2 y-axes
    # plt.figure(figsize=(8, 5))
    # ax1 = plt.gca()
    # ax2 = ax1.twinx()
    #
    # ax1.plot(times, df['TotalSuccessfulHandoverCount'], label='Successful HO', color='tab:green')
    # ax2.plot(times, df['TotalFailedHandoverCount'], label='Failed HO', color='tab:red')
    #
    # ax1.set_xlabel('Time')
    # ax1.set_ylabel('Successful HO Count', color='tab:green')
    # ax2.set_ylabel('Failed HO Count', color='tab:red')
    #
    # ax1.grid(True)
    # plt.title('Successful and Failed Handover Count Over Time')
    # ax1.legend(loc='upper left')
    # ax2.legend(loc='upper right')
    #
    # setup_time_axis(ax1)
    # plt.tight_layout()
    # plt.savefig(f"{file_prefix}_suc_failed_ho.png", format="png", dpi=200)
    # plt.show()
    # plt.close()


def plot_rsu_config(rsu_config: list[RsuConfig], name: str):
    background = get_grid()

    fig, ax = plt.subplots(figsize=(5, 5))

    ax.imshow(background, cmap='gray')

    for i, conf in enumerate(rsu_config):
        color = VEC_STATION_COLORS[i + 10001]
        ax.add_patch(Rectangle((conf.pos[0] - 3, conf.pos[1] - 3), 6, 6, facecolor=color))
        range_circle = Circle(conf.pos, conf.range, color=color, fill=False, linestyle='--')
        ax.add_patch(range_circle)

    ax.set_xlim(0, 200)
    ax.set_ylim(0, 200)
    ax.set_aspect('equal')
    ax.set_xlabel('')
    ax.set_ylabel('')
    ax.set_xticks([])
    ax.set_yticks([])
    fig.tight_layout()
    filename = f'rsu_config_{name}.png'
    fig.savefig(filename, format='png', dpi=200, transparent=True)
    plt.show()


# Example configurations for Sparse and Dense scenarios
results_creteil_sparse = [
    ("results_creteil-morning_4-full", "Morning Full Capacity"),
    ("results_creteil-morning_4-half", "Morning Half Capacity"),
    ("results_creteil-evening_4-full", "Evening Full Capacity"),
    ("results_creteil-evening_4-half", "Evening Half Capacity"),
]

results_creteil_dense = [
    ("results_creteil-morning_9-full", "Morning Full Capacity"),
    ("results_creteil-morning_9-half", "Morning Half Capacity"),
    ("results_creteil-morning_9-quarter", "Morning Quarter Capacity"),
    ("results_creteil-evening_9-full", "Evening Full Capacity"),
    ("results_creteil-evening_9-half", "Evening Half Capacity"),
    ("results_creteil-evening_9-quarter", "Evening Quarter Capacity"),
]

results_creteil_dense_vs_sparse = [
    ("results_creteil-morning_4-full", "Sparse & Full Capacity"),
    ("results_creteil-morning_4-half", "Sparse & Half Capacity"),
    ("results_creteil-morning_9-full", "Dense & Full Capacity"),
    ("results_creteil-morning_9-half", "Dense & Half Capacity"),
    ("results_creteil-morning_9-quarter", "Dense & Quarter Capacity"),
]

results_creteil_failure = [
    ("results_creteil-morning_3-fail-full", "Morning Full Capacity"),
    ("results_creteil-morning_3-fail-half", "Morning Half Capacity"),
]

results_tradition_vs_base = [
    ("results_creteil-morning_4-full", "Sparse & Full Capacity"),
    ("results_creteil-morning_4-half", "Sparse & Half Capacity"),
    ("results_creteil-morning_9-full", "Dense & Full Capacity"),
    ("results_creteil-morning_9-half", "Dense & Half Capacity"),
    ("results_creteil-morning_9-quarter", "Dense & Quarter Capacity"),
]


def plot_total_ho_frequency(configs, title, field):
    # Prepare data
    data = []
    for filename, res_title in configs:
        df = pd.read_csv(f"../results/{filename}.csv")
        df = df.sort_values(by='Model', key=lambda x: x.map(custom_sort_key))
        data.append((filename, df, res_title))

    # Extract total handover frequency data
    ho_data_2 = []

    arhc = ['ARHC-Oracle', 'ARHC-10s', 'ARHC-20s']
    traditional = ['EarliestHO', 'LatestHO', 'NearestRSU']
    done = defaultdict(lambda: False)

    group_names = []

    for filename, df, res_title in data:
        group_names.append(res_title)
        ho_data_2.append([df[df['Model'] == model][field].sum() for model in arhc])
        is_sparse = '4' in filename
        if is_sparse and done['sparse']:
            continue
        if not is_sparse and done['dense']:
            continue

        done['sparse' if is_sparse else 'dense'] = True
        # group_names.append("Sparse" if is_sparse else "Dense")
        ho_data_2.append([df[df['Model'] == model][field].sum() for model in traditional])

    # Swap entry 1 and 2
    ho_data_2[1], ho_data_2[2] = ho_data_2[2], ho_data_2[1]
    # Swap entry 4 and 5_2_2_2
    ho_data_2[4], ho_data_2[5] = ho_data_2[5], ho_data_2[4]
    # Swap entry 5 and 6_2_2_2
    ho_data_2[5], ho_data_2[6] = ho_data_2[6], ho_data_2[5]

    ho_data = list(map(list, zip(*ho_data_2)))

    # Determine if a break is needed
    break_threshold = 20000
    max_value = max(max(x) for x in ho_data)
    needs_break = max_value > break_threshold

    # w = 3 * len(configs)
    w = 12
    # Plotting
    if needs_break:
        fig, (ax, ax2) = plt.subplots(2, 1, sharex=True, figsize=(w, 8),
                                      gridspec_kw={'height_ratios': [1, 6], 'hspace': 0.07})
    else:
        fig, ax2 = plt.subplots(figsize=(w, 8))

    bar_width = 0.2
    gap_width = 0.2  # Width of the gap between groups
    margin = 0.03
    offset = 0.4
    index = np.array([0, 1, 2, 3 + offset, 4 + offset, 5 + offset, 6 + offset]) * (
            len(ho_data) * bar_width + gap_width)  # Add space between groups

    colors = plt.get_cmap('Set1', 6)

    for i, counts in enumerate(ho_data):
        color = [colors(i) for _ in range(5)]
        color.insert(2, colors(i + 3))
        color.append(colors(i + 3))
        if needs_break:
            ax.bar(index + i * bar_width, counts, bar_width - margin, label="a", color=color, edgecolor='black')
        ax2.bar(index + i * bar_width, counts, bar_width - margin, label="a", color=color, edgecolor='black')

    if needs_break:
        # Set the y-axis limits for the break
        ax.set_ylim(break_threshold, max_value)
        ax2.set_ylim(0, break_threshold)

        # Hide the spines between ax and ax2
        ax.spines['bottom'].set_visible(False)
        ax2.spines['top'].set_visible(False)
        ax.xaxis.tick_top()
        ax.tick_params(labeltop=False)  # Don't put tick labels at the top
        ax2.xaxis.tick_bottom()

        # Add diagonal lines to indicate the break
        d = .010  # How big to make the diagonal lines in axes coordinates
        kwargs = dict(transform=ax.transAxes, color='k', clip_on=False)
        ax.plot((-d, +d), (-5 * d, +5 * d), **kwargs)  # Top-left diagonal
        ax.plot((1 - d, 1 + d), (-5 * d, +5 * d), **kwargs)  # Top-right diagonal

        kwargs.update(transform=ax2.transAxes)  # Switch to the bottom axes
        ax2.plot((-d, +d), (1 - d, 1 + d), **kwargs)  # Bottom-left diagonal
        ax2.plot((1 - d, 1 + d), (1 - d, 1 + d), **kwargs)  # Bottom-right diagonal

    vertical_line_position = 2 + offset - gap_width / 4 + 0.02
    if needs_break:
        ax.axvline(x=vertical_line_position, color='gray', linestyle='--')
    ax2.axvline(x=vertical_line_position, color='gray', linestyle='--')

    ax2.set_xlabel('Configurations', fontsize=14)
    ax2.set_ylabel('Number of Handovers', fontsize=14)
    ax2.set_xticks(index + bar_width * (len(ho_data) - 1) / 2)
    x_ticks = group_names
    x_ticks.insert(2, "Sparse\n(cap. indep.)")
    x_ticks.append("Dense\n(cap. indep.)")
    ax2.set_xticklabels(x_ticks, rotation=0, ha='center', fontsize=12)
    legend_loc = "lower left" if not needs_break else "upper left"
    # ax2.legend(title="Handover Coordination Strategy", loc=legend_loc, fontsize=12, title_fontsize=14)
    legend_colors = [colors(i) for i in range(6)]
    legend_labels = ['ARHC Oracle', 'ARHC 10s', 'ARHC 20s', 'Earliest HO', 'Latest HO', 'Nearest RSU']
    ax2.legend(handles=[plt.Line2D([0], [0], color=color, lw=12) for color in legend_colors], labels=legend_labels,
               title="HO Coordination Strategy", loc=legend_loc, fontsize=12, title_fontsize=14)
    title_ax = ax if needs_break else ax2
    title_ax.set_title(
        f"Number of Handovers per Configuration", fontsize=20)
    ax2.grid(True, linestyle='--', alpha=0.7)
    if needs_break:
        ax.grid(True, linestyle='--', alpha=0.7)
    plt.tight_layout()
    plt.savefig(f'{unidecode.unidecode(title).strip().lower().replace(" ", "_")}.png',
                format="png", dpi=200, transparent=True)
    plt.show()


def plot_boxplot(configs, y_axis, field, title, percentage=False):
    # Prepare data
    data = []
    for filename, res_title in configs:
        df = pd.read_csv(f"../results/{filename}.csv")
        df = df.sort_values(by='Model', key=lambda x: x.map(custom_sort_key))
        data.append((filename, df, res_title))

    # Extract total handover frequency data
    qos_data = {}
    for filename, df, res_title in data:
        for model in df['Model'].unique():
            if model.startswith('ARHC-') and model not in ['ARHC-Oracle', 'ARHC-10s', 'ARHC-20s']:
                continue
            if model not in qos_data:
                qos_data[model] = []
            details_file = f"../results/runs/{filename.replace('results', 'result')}_{model.lower()}_model_vars.csv"
            # Read using pands and extract column MinQos
            df = pd.read_csv(details_file)
            qos_values = df[field][1:-1]  # Ignore first and last due to outliers (no vehicles)
            qos_data[model].append(qos_values)

    fig, ax = plt.subplots(figsize=(12, 8))

    bar_width = 0.2
    small_gap_width = 0.1  # Smaller gap between the first three values
    large_gap_width = 0.2  # Width of the gap between groups
    margin = 0.03
    offset = 0.2
    offset_from = 1 if len(configs) == 3 else 2
    base_arr = np.arange(len(configs))
    base_arr = base_arr.astype(np.float64)
    base_arr[offset_from:] += offset
    index = base_arr * (
            len(qos_data) * bar_width + small_gap_width + large_gap_width)  # Add space between groups

    colors = plt.get_cmap('Set1', len(qos_data))
    legend_labels = []
    legend_colors = []

    avg_color = plt.get_cmap('Set1', 10)(7)

    for i, (model, counts) in enumerate(qos_data.items()):
        if i >= 3:
            positions = index + i * bar_width + small_gap_width / 2
        else:
            positions = index + i * bar_width - small_gap_width / 2
        color = colors(i)
        ax.boxplot(counts, positions=positions, widths=bar_width - margin, patch_artist=True,
                   boxprops=dict(facecolor=color),
                   medianprops=dict(color='black'), whiskerprops=dict(color='black'), capprops=dict(color='black'),
                   flierprops=dict(marker='o', color='gray', alpha=0.4, markersize=2),
                   whis=[1, 99])  # Set lower whisker to 9th percentile and upper whisker to 91st percentile
        averages = [np.mean(c) for c in counts]
        ax.scatter(positions, averages, color=color, edgecolors='black', linewidths=1, s=180, zorder=3, label='Average' if i == 0 else "", marker='D')
        legend_labels.append(model)
        legend_colors.append(color)

    vertical_line_position = offset_from + 0.42
    ax.axvline(x=vertical_line_position, color='gray', linestyle='--')

    ax.set_xlabel('Configurations', fontsize=14)
    ax.set_ylabel(y_axis, fontsize=14)
    if percentage:
        plt.gca().yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{x:.0%}'))
    ax.set_xticks(index + bar_width * (len(qos_data) - 1) / 2)
    ax.set_xticklabels([res_title for _, _, res_title in data], rotation=0, ha='center', fontsize=12)
    legend_pos = "lower left" if field == "MinQoS" else "upper left"
    legend_labels = ['ARHC Oracle', 'ARHC 10s', 'ARHC 20s', 'Earliest HO', 'Latest HO', 'Nearest RSU']
    ax.legend(handles=[plt.Line2D([0], [0], color=color, lw=12) for color in legend_colors] +
                      [plt.Line2D([0], [0], color=avg_color, marker='D', lw=0, markersize=10)],
              labels=legend_labels + ['Average', 'P01'],
              title="HO Coordination Strategy", loc=legend_pos, fontsize=12, title_fontsize=14)
    ax.set_title(title, fontsize=20)
    ax.grid(True, linestyle='--', alpha=0.7)
    plt.tight_layout()
    plt.savefig(f'{unidecode.unidecode(y_axis).strip().lower().replace(" ", "_")}.png',
                format="png", dpi=200, transparent=True)
    plt.show()


def plot_boxplot_gini(configs, y_axis, field, title, percentage=False):
    # Prepare data
    data = []
    for filename, res_title in configs:
        df = pd.read_csv(f"../results/{filename}.csv")
        df = df.sort_values(by='Model', key=lambda x: x.map(custom_sort_key))
        data.append((filename, df, res_title))

    # Extract total handover frequency data
    qos_data = {}
    for filename, df, res_title in data:
        for model in df['Model'].unique():
            if model.startswith('ARHC-') and model not in ['ARHC-Oracle', 'ARHC-10s', 'ARHC-20s']:
                continue
            if model not in qos_data:
                qos_data[model] = []
            details_file = f"../results/runs/{filename.replace('results', 'result')}_{model.lower()}_model_vars.csv"
            # Read using pands and extract column MinQos
            df = pd.read_csv(details_file)
            qos_values = df[field][1:-1]  # Ignore first and last due to outliers (no vehicles)
            qos_data[model].append(qos_values)

    ho_data_2 = []

    arhc = ['ARHC-Oracle', 'ARHC-10s', 'ARHC-20s']
    traditional = ['EarliestHO', 'LatestHO', 'NearestRSU']
    done = defaultdict(lambda: False)

    group_names = []

    for filename, df, res_title in data:
        group_names.append(res_title)
        ho_data_2.append([])
        for model in arhc:
            details_file = f"../results/runs/{filename.replace('results', 'result')}_{model.lower()}_model_vars.csv"
            df = pd.read_csv(details_file)
            qos_values = df[field][1:-1]  # Ignore first and last due to outliers (no vehicles)
            ho_data_2[-1].append(qos_values)
        is_sparse = '4' in filename
        if is_sparse and done['sparse']:
            continue
        if not is_sparse and done['dense']:
            continue

        ho_data_2.append([])
        for model in traditional:
            details_file = f"../results/runs/{filename.replace('results', 'result')}_{model.lower()}_model_vars.csv"
            df = pd.read_csv(details_file)
            qos_values = df[field][1:-1]
            ho_data_2[-1].append(qos_values)

        done['sparse' if is_sparse else 'dense'] = True
        # group_names.append("Sparse" if is_sparse else "Dense")
        # ho_data_2.append([df[df['Model'] == model][field].sum() for model in traditional])

    # Swap entry 1 and 2
    ho_data_2[1], ho_data_2[2] = ho_data_2[2], ho_data_2[1]
    # Swap entry 4 and 5_2_2_2
    ho_data_2[4], ho_data_2[5] = ho_data_2[5], ho_data_2[4]
    # Swap entry 5 and 6_2_2_2
    ho_data_2[5], ho_data_2[6] = ho_data_2[6], ho_data_2[5]

    qos_data = list(map(list, zip(*ho_data_2)))

    fig, ax = plt.subplots(figsize=(12, 8))

    bar_width = 0.2
    small_gap_width = 0.1  # Smaller gap between the first three values
    large_gap_width = 0.2  # Width of the gap between groups
    margin = 0.03
    offset = 0.2
    offset_from = 3
    base_arr = np.arange(7)
    base_arr = base_arr.astype(np.float64)
    base_arr[offset_from:] += offset
    index = base_arr * (len(qos_data) * bar_width + large_gap_width)  # Add space between groups

    colors = plt.get_cmap('Set1', 6)
    legend_colors = []

    for i, counts in enumerate(qos_data):
        positions = index + (i - 1) * bar_width
        color = [colors(i) for _ in range(5)]
        color.insert(2, colors(i + 3))
        color.append(colors(i + 3))
        for val, pos, col in zip(counts, positions, color):
            ax.boxplot([val], positions=[pos], widths=bar_width - margin, patch_artist=True,
                       boxprops=dict(facecolor=col),
                       medianprops=dict(color='black'), whiskerprops=dict(color='black'), capprops=dict(color='black'),
                       flierprops=dict(marker='o', color='gray', alpha=0.4, markersize=2))
        legend_colors.append(color)

    vertical_line_position = offset_from - 1 + 0.08
    ax.axvline(x=vertical_line_position, color='gray', linestyle='--')

    ax.set_xlabel('Configurations', fontsize=14)
    ax.set_ylabel(y_axis, fontsize=14)
    if percentage:
        plt.gca().yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{x:.0%}'))
    ax.set_xticks(index)
    x_labels = [res_title for _, _, res_title in data]
    x_labels.insert(2, "Sparse\n(cap. indep.)")
    x_labels.append("Dense\n(cap. indep.)")
    ax.set_xticklabels(x_labels, rotation=0, ha='center', fontsize=12)
    legend_colors = [colors(i) for i in range(6)]
    legend_pos = "lower left" if field == "MinQoS" else "upper left"
    legend_labels = ['ARHC Oracle', 'ARHC 10s', 'ARHC 20s', 'Earliest HO', 'Latest HO', 'Nearest RSU']
    ax.legend(handles=[plt.Line2D([0], [0], color=color, lw=12) for color in legend_colors],
              labels=legend_labels,
              title="HO Coordination Strategy", loc=legend_pos, fontsize=12, title_fontsize=14)
    ax.set_title(title, fontsize=20)
    ax.grid(True, linestyle='--', alpha=0.7)
    plt.tight_layout()
    plt.savefig(f'{unidecode.unidecode(y_axis).strip().lower().replace(" ", "_")}.png',
                format="png", dpi=200, transparent=True)
    plt.show()


# Main function to visualize results
def main():
    # visualize_results(results_creteil_sparse, "Créteil Sparse")
    # visualize_results(results_creteil_dense, "Créteil Dense")
    # visualize_results(results_creteil_dense_vs_sparse, "Créteil Morning Sparse vs Dense", plot_ho=False)
    # visualize_results(results_creteil_failure, "Créteil Failure")

    # plot_metrics_over_time("creteil-morning", "4-half", "arhc-01s", morning=True)
    # plot_metrics_over_time("creteil-evening", "4-full", "arhc-01s", morning=False)
    # plot_metrics_over_time("creteil-morning", "9-quarter", "arhc-01s", morning=True)
    # plot_metrics_over_time("creteil-evening", "9-full", "arhc-01s", morning=False)
    # plot_metrics_over_time("creteil-morning", "3-fail-full", "arhc-01s", morning=True)
    # plot_metrics_over_time("creteil-morning", "3-fail-half", "arhc-01s", morning=True)

    # plot_rsu_config(CRETEIL_4_RSU_FULL_CAPA_CONFIG, "creteil_4")
    # plot_rsu_config(CRETEIL_9_RSU_FULL_CAPA_CONFIG, "creteil_9")
    # plot_rsu_config(CRETEIL_3_FAIL_RSU_FULL_CAPA_CONFIG, "creteil_3_fail")

    cap_suffix = " Cap."

    plot_total_ho_frequency([
        ("results_creteil-morning_4-full", "Sparse NW\nFull" + cap_suffix),
        ("results_creteil-morning_4-half", "Sparse NW\nHalf" + cap_suffix),
        ("results_creteil-morning_9-full", "Dense NW\nFull" + cap_suffix),
        ("results_creteil-morning_9-half", "Dense NW\nHalf" + cap_suffix),
        ("results_creteil-morning_9-quarter", "Dense NW\nQuarter" + cap_suffix),
    ], "ho", "HO_Total")

    plot_boxplot([
        ("results_creteil-morning_4-half", "Sparse NW\nHalf" + cap_suffix),
        ("results_creteil-morning_9-half", "Dense NW\nHalf" + cap_suffix),
        ("results_creteil-morning_9-quarter", "Dense NW\nQuarter" + cap_suffix),
    ], "Minimum QoS", "MinQoS", "Minimum QoS per Configuration", percentage=True)

    plot_boxplot_gini([
        ("results_creteil-morning_4-full", "Sparse NW\nFull" + cap_suffix),
        ("results_creteil-morning_4-half", "Sparse NW\nHalf" + cap_suffix),
        ("results_creteil-morning_9-full", "Dense NW\nFull" + cap_suffix),
        ("results_creteil-morning_9-half", "Dense NW\nHalf" + cap_suffix),
        ("results_creteil-morning_9-quarter", "Dense NW\nQuarter" + cap_suffix),
    ], "Load Distribution (Gini Coefficient)", "GiniLoad",
        "Load Distribution Inequality (Gini Coefficient) per Configuration", percentage=False)


if __name__ == "__main__":
    main()
