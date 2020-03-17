"""
Plotting related functions
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib import rcParams
from matplotlib.colors import LinearSegmentedColormap, Normalize, to_hex
import scanpy as sc
from scanpy.plotting._tools.scatterplots import plot_scatter

from ._diffexp import extract_de_table
from ._utils import pseudo_bulk

sc_default_10 = rcParams['axes.prop_cycle'].by_key()['color']
sc_default_26 = sc.plotting.palettes.default_26
sc_default_64 = sc.plotting.palettes.default_64

def expression_colormap(background_level=0.01):
    """Returns a nice color map for highlighting gene expression
    """
    background_nbin = int(100 * background_level)
    reds = plt.cm.Reds(np.linspace(0, 1, 100-background_nbin))
    greys = plt.cm.Greys_r(np.linspace(0.7, 0.8, background_nbin))
    palette = np.vstack([greys, reds])
    return LinearSegmentedColormap.from_list('expression', palette)


def make_palette(n, cmap=None, hide_last=False):
    """Returns a color palette with specified number of colors
    """
    i = int(hide_last)
    if cmap is None:
        palette = (sc_default_10[0:(n-i)] if n <= 10 + i else
                sc_default_26[0:(n-i)] if n <= 26 + i else
                sc_default_64[0:(n-i)] if n<= 64 + i else
                ['grey'] * n)
    else:
        color_map = plt.get_cmap(cmap)
        palette = [to_hex(color_map(j)) for j in range(n-i)]

    if hide_last:
        palette.append('#E9E9E9')
    return palette


def clear_colors(ad, slots=None):
    color_slots = [k for k in ad.uns.keys() if k.endswith('_colors')]
    if isinstance(slots, str):
        slots = [slots]
    elif slots is None:
        slots = [s.replace('_colors', '') for s in color_slots]
    if isinstance(slots, (tuple, list)):
        slots = [s for s in slots if f'{s}_colors' in color_slots]
    for s in slots:
        del ad.uns[f'{s}_colors']


def _is_numeric(x):
    return x.dtype.kind in ('i', 'f')


def cross_table(adata, x, y, normalise=None, highlight=None, subset=None):
    """Make a cross table comparing two categorical annotations
    """
    x_attr = adata.obs[x]
    y_attr = adata.obs[y]
    if subset is not None:
        x_attr = x_attr[subset]
        y_attr = y_attr[subset]
    assert not _is_numeric(x_attr.values), f'Can not operate on numerical {x}'
    assert not _is_numeric(y_attr.values), f'Can not operate on numerical {y}'
    crs_tbl = pd.crosstab(x_attr, y_attr)
    if normalise == 'x':
        x_sizes = x_attr.groupby(x_attr).size().values
        crs_tbl = (crs_tbl.T / x_sizes * 100).round(2).T
    elif normalise == 'y':
        y_sizes = x_attr.groupby(y_attr).size().values
        crs_tbl = (crs_tbl / y_sizes * 100).round(2)
    elif normalise == 'xy':
        x_sizes = x_attr.groupby(x_attr).size().values
        crs_tbl = (crs_tbl.T / x_sizes * 100).T
        y_sizes = crs_tbl.sum(axis=0)
        crs_tbl = (crs_tbl / y_sizes * 100).round(2)
    elif normalise == 'yx':
        y_sizes = x_attr.groupby(y_attr).size().values
        crs_tbl = (crs_tbl / y_sizes * 100).round(2)
        x_sizes = crs_tbl.sum(axis=1)
        crs_tbl = (crs_tbl.T / x_sizes * 100).round(2).T
    if highlight is not None:
        return crs_tbl.style.background_gradient(cmap='viridis', axis=highlight)
    return crs_tbl


def set_figsize(dim):
    if len(dim) == 2 and (isinstance(dim[0], (int, float))
            and isinstance(dim[1], (int, float))):
        rcParams.update({'figure.figsize': dim})
    else:
        raise ValueError(f'Invalid {dim} value, must be an iterable of '
                          'length two in the form of (width, height).')


def plot_df_heatmap(
        df,
        cmap='viridis',
        title=None,
        figsize=(7, 7),
        rotation=90,
        save=None,
        **kwargs,
):
    fig, ax = plt.subplots(figsize=figsize)
    im = ax.imshow(df, cmap=cmap, aspect='auto', **kwargs)
    if 0 < rotation < 90:
        horizontalalignment = 'right'
    else:
        horizontalalignment = 'center'
    plt.xticks(
        range(len(df.columns)),
        df.columns,
        rotation=rotation,
        horizontalalignment=horizontalalignment,
    )
    plt.yticks(range(len(df.index)), df.index)
    if title:
        fig.suptitle(title)
    fig.colorbar(im)
    if save:
        plt.savefig(fname=save, bbox_inches='tight', pad_inches=0.1)


def _log_hist(x, bins=50, min_x=None, max_x=None, xlim=None, ax=None):
    x_copy = x.copy()
    if max_x is None:
        max_x = x[np.isfinite(x)].max()
    x_copy[x > max_x] = max_x
    if min_x is None:
        min_x1 = x[x>0].min()
        min_x = 10** (np.log10(min_x1) - (np.log10(max_x) - np.log10(min_x1))/(bins - 1))
    x_copy[x < min_x] = min_x

    log_bins = np.logspace(np.log10(min_x), np.log10(max_x), bins)
    if ax:
        ax.hist(x_copy, bins=log_bins)
        ax.set_xscale('log')
    else:
        fig, ax = plt.subplots()
        ax.hist(x_copy, bins=log_bins)
        ax.set_xscale('log')
        return ax


def dotplot2(
        adata, keys, groupby=None, min_group_size=0, min_presence=0, use_raw=None,
        mean_only_expressed=False, second_key_dependent_fraction=False,
        vmin=0, vmax=1, dot_min=None, dot_max=None, color_map='Reds', swap_axis=False,
        legend_loc='right', title='', title_loc='top', omit_xlab=False, omit_ylab=False,
        ax=None, save=None, save_dpi=80, **kwargs):
    if isinstance(keys, str):
        keys = [keys]
    if not isinstance(keys, (list, tuple)):
        raise ValueError(f'keys must be a tuple/list of obs keys or var_names')

    if second_key_dependent_fraction:
        if len(keys) != 2:
            raise ValueError('Exactly two keys requied if `second_key_dependent_fraction=True`')

    cmap = plt.get_cmap(color_map)
    if use_raw or (use_raw is None and adata.raw):
        ad = adata.raw
    else:
        ad = adata

    if groupby is None:
        groups = pd.Series(np.ones(adata.n_obs)).astype(str).astype('category')
        n_group = 1
    elif groupby in adata.obs.columns:
        groups = adata.obs[groupby]
        if groups.dtype.name != 'category':
            groups = groups.astype('category')
    else:
        raise ValueError(f'{groupby} not found')
    grouping = list(groups.cat.categories)

    n_obs = ad.shape[0]
    n_key = len(keys)
    y = np.zeros((n_key, n_obs))
    for i in range(n_key):
        key = keys[i]
        if key in adata.obs.columns:
            y[i] = adata.obs[key].values
        elif key in ad.var_names:
            y[i] = ad[:, key].X
        else:
            sc.logging.warn(f'{key} not found')
            y[i] = np.zeros(n_obs)

    df = pd.DataFrame(y.T, columns=keys)
    df['group'] = groups.reset_index(drop=True)
    df['group'].cat.set_categories(grouping, inplace=True)
    group_size = df.groupby('group').agg('size')
    if min_group_size:
        df = df.loc[df['group'].isin(group_size.index[group_size.values >= min_group_size]), :]
    n_group = df['group'].cat.categories.size

    if second_key_dependent_fraction:
        exp_cnt = df.groupby('group')[keys].apply(lambda g: ((g>0).sum(axis=1)==2).sum()).values
        frac = df.groupby('group')[keys].apply(lambda g: ((g>0).sum(axis=1)==2).mean())
        group_label = frac.index.values
        frac = frac.values
        avg0 = df.groupby('group')[[keys[0]]].apply(lambda g: g.mean(axis=0)).values
        avg1 = df.groupby('group')[[keys[0]]].apply(lambda g: g.sum(axis=0) / (g>0).sum(axis=0)).fillna(0).values
        avg = avg1 if mean_only_expressed else avg0
        n_key = 1
    else:
        exp_cnt = df.groupby('group')[keys].apply(lambda g: (g>0).sum(axis=0)).values
        frac = df.groupby('group')[keys].apply(lambda g: (g>0).mean(axis=0))
        group_label = frac.index.values
        frac = frac.values
        avg0 = df.groupby('group')[keys].apply(lambda g: g.mean(axis=0)).values
        avg1 = df.groupby('group')[keys].apply(lambda g: g.sum(axis=0) / (g>0).sum(axis=0)).fillna(0).values
        avg = avg1 if mean_only_expressed else avg0

    frac[exp_cnt<min_presence] = 0
    avg[exp_cnt<min_presence] = 0

    if dot_max is None:
        dot_max = np.ceil(np.max(frac) * 10) / 10
    else:
        if dot_max < 0 or dot_max > 1:
            raise ValueError("`dot_max` value has to be between 0 and 1")
    if dot_min is None:
        dot_min = 0
    else:
        if dot_min < 0 or dot_min > 1:
            raise ValueError("`dot_min` value has to be between 0 and 1")

    if dot_min != 0 or dot_max != 1:
        # clip frac between dot_min and  dot_max
        frac = np.clip(frac, dot_min, dot_max)
        old_range = dot_max - dot_min
        # re-scale frac between 0 and 1
        frac = ((frac - dot_min) / old_range)

    frac = frac.T.flatten()
    avg = avg.T.flatten()
    dot_sizes = (frac * 10) ** 2
    normalize = Normalize(vmin=vmin, vmax=vmax)
    dot_colors = cmap(normalize(avg))

    legend_loc = 'none' if ax else legend_loc
    fig_width = 0.5 + (n_key if swap_axis else n_group) * 0.25 + 0.25 * int(legend_loc == 'right')
    fig_height = 0.5 + (n_group if swap_axis else n_key) * 0.2 + 0.25 * int(legend_loc == 'bottom')

    rcParams.update({'figure.figsize': (fig_width, fig_height)})
    if legend_loc == 'right':
        fig, axs = plt.subplots(ncols=2, nrows=1, gridspec_kw={'width_ratios': [fig_width-0.25, 0.25], 'wspace': 0.25/(n_key if swap_axis else n_group)})
    elif legend_loc == 'bottom':
        fig, axs = plt.subplots(ncols=1, nrows=2, gridspec_kw={'height_ratios': [fig_height-0.25, 0.25], 'hspace': 0.25/(n_group if swap_axis else n_key)})
    elif not ax:
        fig, axs = plt.subplots(ncols=1, nrows=1)
        axs = [axs]
    else:
        axs = [ax]
    main = axs[0]

    if legend_loc == 'bottom':
        main.xaxis.tick_top()
    if swap_axis:
        main.scatter(y=np.tile(range(n_group), n_key), x=np.repeat(np.arange(n_key)[::-1], n_group), color=dot_colors[::-1], s=dot_sizes[::-1], cmap=cmap, norm=None, edgecolor='none', **kwargs)
        main.set_xticks(range(n_key))
        main.set_xticklabels(keys, rotation=270)
        main.set_xlim(-0.5, n_key - 0.5)
        main.set_yticks(range(n_group))
        main.set_yticklabels(group_label[::-1])
        main.set_ylim(-0.5, n_group - 0.5)
    else:
        main.scatter(x=np.tile(range(n_group), n_key), y=np.repeat(np.arange(n_key), n_group), color=dot_colors, s=dot_sizes, cmap=cmap, norm=None, edgecolor='none', **kwargs)
        main.set_yticks(range(n_key))
        main.set_yticklabels(keys)
        main.set_ylim(-0.5, n_key - 0.5)
        main.set_xticks(range(n_group))
        main.set_xticklabels(group_label, rotation=270)
        main.set_xlim(-0.5, n_group - 0.5)
    if title:
        if title_loc == 'top':
            main.set_title(title, fontsize=15)
        elif title_loc == 'right':
            title_ax = axs[1] if legend_loc == 'right' else main
            ylab_position = 'left' if legend_loc == 'right' else 'right'
            ylab_pad = 0 if legend_loc == 'right' else 20
            title_ax.yaxis.set_label_position(ylab_position)
            title_size = min(15, 100*fig_height/len(title))
            title_ax.set_ylabel(title, rotation=270, labelpad=ylab_pad, fontsize=title_size)
    if omit_xlab:
        main.tick_params(axis='x', bottom=False, labelbottom=False)
    if omit_ylab:
        main.tick_params(axis='y', left=False, labelleft=False)

    if legend_loc in ('right', 'bottom'):
        diff = dot_max - dot_min
        if 0.2 < diff <= 0.6:
            step = 0.1
        elif 0.06 < diff <= 0.2:
            step = 0.05
        elif 0.03 < diff <= 0.06:
            step = 0.02
        elif diff <= 0.03:
            step = 0.01
        else:
            step = 0.2
        # a descending range that is afterwards inverted is used
        # to guarantee that dot_max is in the legend.
        fracs_legends = np.arange(dot_max, dot_min, step * -1)[::-1]
        if dot_min != 0 or dot_max != 1:
            fracs_values = ((fracs_legends - dot_min) / old_range)
        else:
            fracs_values = fracs_legends
        size = (fracs_values * 10) ** 2
        color = [cmap(normalize(value)) for value in np.repeat(vmax, len(size))]

        # plot size bar
        size_legend = axs[1]
        labels = ["{:.0%}".format(x) for x in fracs_legends]
        if dot_max < 1:
            labels[-1] = ">=" + labels[-1]

        if legend_loc == 'bottom':
            size_legend.scatter(y=np.repeat(0, len(size)), x=range(len(size)), s=size, color=color)
            size_legend.set_xticks(range(len(size)))
            #size_legend.set_xticklabels(labels, rotation=270)
            size_legend.set_xticklabels(["{:.0%}".format(x) for x in fracs_legends], rotation=270)
            # remove y ticks and labels
            size_legend.tick_params(axis='x', bottom=False, labelbottom=True, pad=-2)
            size_legend.tick_params(axis='y', left=False, labelleft=False)
            xmin, xmax = size_legend.get_xlim()
            size_legend.set_xlim(xmin-((n_key if swap_axis else n_group)-1)*0.75, xmax+0.5)
        else:
            size_legend.scatter(np.repeat(0, len(size)), range(len(size)), s=size, color=color)
            size_legend.set_yticks(range(len(size)))
            #size_legend.set_yticklabels(labels)
            size_legend.set_yticklabels(["{:.0%}".format(x) for x in fracs_legends])
            # remove x ticks and labels
            size_legend.tick_params(axis='y', left=False, labelleft=False, labelright=True, pad=-2)
            size_legend.tick_params(axis='x', bottom=False, labelbottom=False)
            ymin, ymax = size_legend.get_ylim()
            size_legend.set_ylim(ymin - ((n_group if swap_axis else n_key)-1)*0.75, ymax+0.5)

        # remove surrounding lines
        size_legend.spines['right'].set_visible(False)
        size_legend.spines['top'].set_visible(False)
        size_legend.spines['left'].set_visible(False)
        size_legend.spines['bottom'].set_visible(False)
        size_legend.grid(False)

    if save:
        fig.savefig(save, bbox_inches='tight', dpi=save_dpi)
        plt.close()

    if ax:
        return fig_width, fig_height

    return main


def plot_qc(adata, groupby=None, groupby_only=False):
    qc_metrics = ('n_counts', 'n_genes', 'percent_mito', 'percent_ribo', 'percent_hb', 'percent_top50')
    for qmt in qc_metrics:
        if qmt not in adata.obs.columns:
            raise ValueError(f'{qmt} not found.')
    if groupby:
        sc.pl.violin(adata, keys=qc_metrics, groupby=groupby, rotation=45, stripplot=False, show=False)
    if not groupby_only:
        sc.pl.violin(adata, keys=qc_metrics, multi_panel=True, stripplot=False)
        old_figsize = rcParams.get('figure.figsize')
        rcParams.update({'figure.figsize': (15,3)})
        fig, ax = plt.subplots(ncols=4, nrows=1)
        sc.pl.scatter(adata, x='n_counts', y='percent_mito', alpha=0.5, ax=ax[0], show=False)
        sc.pl.scatter(adata, x='n_counts', y='percent_top50', alpha=0.5, ax=ax[1], show=False)
        sc.pl.scatter(adata, x='percent_mito', y='percent_ribo', alpha=0.5, ax=ax[2], show=False)
        sc.pl.scatter(adata, x='log1p_n_counts', y='log1p_n_genes', alpha=0.5, ax=ax[3], color=groupby, show=False)
        rcParams.update({'figure.figsize': old_figsize})


def plot_metric_by_rank(
        adata,
        subject='cell',
        metric='n_counts',
        kind='rank',
        nbins=50,
        order=True,
        decreasing=True,
        ax=None,
        title=None,
        hpos=None,
        vpos=None,
        logx=True,
        logy=True,
        swap_axis=False,
        **kwargs,
):
    """Plot metric by rank from top to bottom"""
    kwargs['c'] = kwargs.get('c', 'black')
    metric_names = {
        'n_counts': 'nUMI', 'n_genes': 'nGene', 'n_cells': 'nCell', 'mt_prop': 'fracMT'}
    if subject not in ('cell', 'gene'):
        print('`subject` must be "cell" or "gene".')
        return
    if metric not in metric_names:
        print('`metric` must be "n_counts", "n_genes", "n_cells" or "mt_prop".')
        return

    if metric == 'mt_prop' and 'mt_prop' not in adata.obs.columns:
        if 'mito' in adata.var.columns:
            k_mt = adata.var.mito.astype(bool).values
        else:
            k_mt = adata.var_names.str.startswith('MT-')
        if sum(k_mt) > 0:
            adata.obs['mt_prop'] = np.squeeze(
                np.asarray(adata.X[:, k_mt].sum(axis=1))) / adata.obs['n_counts'] * 100

    if not ax:
        fig, ax = plt.subplots()

    if kind == 'rank':
        order_modifier = -1 if decreasing else 1

        if subject == 'cell':
            if metric not in adata.obs.columns:
                if metric == 'n_counts':
                    adata.obs['n_counts'] = adata.X.sum(axis=1).A1
                if metric == 'n_genes':
                    adata.obs['n_genes'] = (adata.X>0).sum(axis=1).A1
            if swap_axis:
                x = 1 + np.arange(adata.shape[0])
                y = adata.obs[metric].values
                if order is not False:
                    k = np.argsort(order_modifier * y) if order is True else order
                    y = y[k]
            else:
                y = 1 + np.arange(adata.shape[0])
                x = adata.obs[metric].values
                if order is not False:
                    k = np.argsort(order_modifier * x) if order is True else order
                    x = x[k]
        else:
            if metric not in adata.var.columns:
                if metric == 'n_counts':
                    adata.var['n_counts'] = adata.X.sum(axis=0).A1
            if swap_axis:
                x = 1 + np.arange(adata.shape[1])
                y = adata.var[metric].values
                if order is not False:
                    k = np.argsort(order_modifier * y) if order is True else order
                    y = y[k]
            else:
                y = 1 + np.arange(adata.shape[1])
                x = adata.var[metric].values
                if order is not False:
                    k = np.argsort(order_modifier * x) if order is True else order
                    x = x[k]

        if kwargs['c'] is not None and not isinstance(kwargs['c'], str):
            kwargs_c = kwargs['c'][k]
            del kwargs['c']
            ax.scatter(x, y, c=kwargs_c, **kwargs)
        else:
            marker = kwargs.get('marker', '-')
            ax.plot(x, y, marker, **kwargs)

        if logy:
            ax.set_yscale('log')
        if swap_axis:
            ax.set_xlabel('Rank')
        else:
            ax.set_ylabel('Rank')

    elif kind == 'hist':
        del kwargs['c']
        if subject == 'cell':
            value = adata.obs[metric]
            logbins = np.logspace(np.log10(np.min(value[value>0])), np.log10(np.max(adata.obs[metric])), nbins)
            h = ax.hist(value[value>0], logbins, **kwargs)
            y = h[0]
            x = h[1]
        else:
            value = adata.var[metric]
            logbins = np.logspace(np.log10(np.min(value[value>0])), np.log10(np.max(adata.var[metric])), nbins)
            h = ax.hist(value[value>0], logbins, **kwargs)
            y = h[0]
            x = h[1]

        ax.set_ylabel('Count')

    if hpos is not None:
        ax.hlines(hpos, xmin=x.min(), xmax=x.max(), linewidth=1, colors='red')
    if vpos is not None:
        ax.vlines(vpos, ymin=y.min(), ymax=y.max(), linewidth=1, colors='green')
    if logx:
        ax.set_xscale('log')
    if swap_axis:
        ax.set_ylabel(metric_names[metric])
    else:
        ax.set_xlabel(metric_names[metric])
    if title:
        ax.set_title(title)
    ax.grid(linestyle='--')
    if 'label' in kwargs:
        ax.legend(loc='upper right' if decreasing else 'upper left')

    return ax


def plot_embedding(
        adata, basis, groupby, color=None, annot='full', highlight=None, size=None,
        save=None, savedpi=300, figsize=(4,4), **kwargs):
    set_figsize(figsize)
    if f'X_{basis}' not in adata.obsm.keys():
        raise KeyError(f'"X_{basis}" not found in `adata.obsm`.')
    if isinstance(groupby, (list, tuple)):
        groupby = groupby[0]
    if groupby not in adata.obs.columns:
        raise KeyError(f'"{groupby}" not found in `adata.obs`.')
    if adata.obs[groupby].dtype.name != 'category':
        raise ValueError(f'"{groupby}" is not categorical.')
    groups = adata.obs[groupby].copy()
    categories = list(adata.obs[groupby].cat.categories)
    rename_dict = {ct: f'{i}: {ct} (n={(adata.obs[groupby]==ct).sum()})' for i, ct in enumerate(categories)}
    restore_dict = {f'{i}: {ct} (n={(adata.obs[groupby]==ct).sum()})': ct for i, ct in enumerate(categories)}

    size_ratio = 1.2

    ad = adata
    marker_size = size
    kwargs['show'] = False
    kwargs['save'] = False
    kwargs['frameon'] = True
    kwargs['legend_loc'] = 'right margin'

    color = groupby if color is None else color
    offset = 0 if 'diffmap' in basis else -1
    xi, yi = 1, 2
    if 'components' in kwargs:
        xi, yi = components
    xi += offset
    yi += offset

    if highlight:
        k = adata.obs[groupby].isin(highlight).values
        ad = adata[~k, :]
        marker_size = size / size_ratio if size else None
    if annot not in (None, False, 'none'):
        adata.obs[groupby].cat.rename_categories(rename_dict, inplace=True)
        if highlight:
            ad.obs[groupby].cat.rename_categories(rename_dict, inplace=True)
    else:
        kwargs['frameon'] = False
        kwargs['title'] = ''
        kwargs['legend_loc'] = None

    fig, ax = plt.subplots()
    try:
        plot_scatter(ad, basis, color=color, ax=ax, size=marker_size, **kwargs)

        if highlight:
            embed = adata.obsm[f'X_{basis}']
            for i, ct in enumerate(categories):
                if ct not in highlight:
                    continue
                k_hl = groups == ct
                ax.scatter(embed[k_hl, xi], embed[k_hl, yi], marker='D', c=adata.uns[f'{groupby}_colors'][i], s=marker_size)
                ax.scatter([], [], marker='D', c=adata.uns[f'{groupby}_colors'][i], label=adata.obs[groupby].cat.categories[i])
            if annot not in (None, False, 'none'):
                ax.legend(frameon=False, loc='center left', bbox_to_anchor=(1, 0.5),
                          ncol=(1 if len(categories) <= 14 else 2 if len(categories) <= 30 else 3))
    finally:
        if annot not in (None, False, 'none'):
            adata.obs[groupby].cat.rename_categories(restore_dict, inplace=True)
    if annot == 'full':
        centroids = pseudo_bulk(adata, groupby, use_rep=f'X_{basis}', FUN=np.median).T
        texts = [ax.text(x=row[xi], y=row[yi], s=f'{i:d}', fontsize=8, fontweight='bold') for i, row in centroids.reset_index(drop=True).iterrows()]
        from adjustText import adjust_text
        adjust_text(texts, ax=ax, text_from_points=False, autoalign=False)
    if save:
        plt.savefig(fname=save, dpi=savedpi, bbox_inches='tight', pad_inches=0.1)


def highlight(adata, basis, groupby, groups, hide_rest=False, figsize=(4, 4), **kwargs):
    set_figsize(figsize)
    old_obs = adata.obs.copy()
    if isinstance(groups, (list, tuple)):
        new_obs = pd.get_dummies(adata.obs[groupby])[groups].astype(bool).astype('category')
        adata.obs = new_obs
        try:
            kwargs['palette'] = ['lightgrey', 'red']
            plot_scatter(adata, basis, color=groups, **kwargs)
        finally:
            adata.obs = old_obs
            clear_colors(adata)
    elif isinstance(groups, dict):
        new_obs = adata.obs[[groupby]].copy()
        for grp_name, grp in groups.items():
            new_obs[grp_name] = new_obs[groupby].astype(str)
            new_obs.loc[~new_obs[groupby].isin(grp), grp_name] = 'others'
            new_obs[grp_name] = new_obs[grp_name].astype('category').cat.reorder_categories(grp + ['others'])
            adata.uns[f'{grp_name}_colors'] = make_palette(len(grp)+1, kwargs.get('palette', None), hide_last=True)
        adata.obs = new_obs
        try:
            if 'palette' in kwargs:
                del kwargs['palette']
            kwargs['title'] = [f'{groupby}: {grp_name}' for grp_name in groups.keys()]
            plot_scatter(adata, basis, color=list(groups.keys()), **kwargs)
        finally:
            adata.obs = old_obs
            clear_colors(adata)


def plot_diffexp(
    adata,
    basis='umap',
    key='rank_genes_groups',
    top_n=4,
    extra_genes=None,
    figsize1=(4,4),
    figsize2=(2.5, 2.5),
    dotsize=None,
    **kwargs
):
    grouping = adata.uns[key]['params']['groupby']
    de_tbl = extract_de_table(adata.uns[key])
    de_tbl = de_tbl.loc[de_tbl.genes.astype(str) != 'nan', :]
    de_genes = list(de_tbl.groupby('cluster').head(top_n)['genes'].values)
    de_clusters = list(de_tbl.groupby('cluster').head(top_n)['cluster'].astype(str).values)
    if extra_genes:
        de_genes.extend(extra_genes)
        de_clusters.extend(['known'] * len(extra_genes))

    rcParams.update({'figure.figsize': figsize1})
    sc.pl.rank_genes_groups(adata, key=key, show=False)

    sc.pl.dotplot(adata, var_names=de_genes, groupby=grouping, show=False)

    expr_cmap = expression_colormap(0.01)
    rcParams.update({'figure.figsize':figsize2})
    plot_scatter(
        adata,
        basis=basis,
        color=de_genes,
        color_map=expr_cmap,
        use_raw=True,
        size=dotsize,
        title=[f'{c}, {g}' for c, g in zip(de_clusters, de_genes)],
        show=False,
        **kwargs,
    )

    rcParams.update({'figure.figsize':figsize1})
    plot_embedding(
        adata, basis=basis, groupby=grouping, size=dotsize, show=False)

    return de_tbl