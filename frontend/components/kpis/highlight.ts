/** The part of LayerChart's series state that drives highlighting. */
export interface SeriesHighlight {
  highlightKey: string | null;
  setHighlight(key: string | null): void;
  onHighlightChange?: () => void;
}

/**
 * Hold `key` highlighted against LayerChart's hover, which sets and clears
 * the highlight as the pointer crosses points and tooltip rows. A null key
 * hands highlighting back to hover.
 */
export function pinHighlight(series: SeriesHighlight, key: string | null) {
  series.onHighlightChange =
    key === null
      ? undefined
      : () => {
          if (series.highlightKey !== key) series.setHighlight(key);
        };
  series.setHighlight(key);
}
