"""
This file contains a class that holds the TimeSeries class. This class is used
to "manage" the time series within PASTAS. It has methods to change a time
series in frequency and extend the time series, without losing the original
data.

August 2017, R.A. Collenteur

"""
from __future__ import print_function, division

from warnings import warn

import pandas as pd
from pastas.utils import get_dt, get_time_offset


class TimeSeries(pd.Series):
    _kind_settings = {
        "oseries": {"freq": "D", "sample_up": None, "sample_down": None,
                    "fill_nan": "drop", "fill_before": None, "fill_after":
                        None},
        "prec": {"freq": "D", "sample_up": "mean", "sample_down": "sum",
                 "fill_nan": 0.0, "fill_before": "mean", "fill_after": "mean"},
        "evap": {"freq": "D", "sample_up": "interpolate", "sample_down": "sum",
                 "fill_nan": "interpolate", "fill_before": "mean",
                 "fill_after": "mean"},
        "well": {"freq": "D", "sample_up": "bfill", "sample_down": "sum",
                 "fill_nan": 0.0, "fill_before": 0.0, "fill_after": 0.0},
        "waterlevel": {"freq": "D", "sample_up": "mean",
                       "sample_down": "interpolate",
                       "fill_nan": "interpolate",
                       "fill_before": "mean", "fill_after": "mean"},
    }
    metadata = {
        "x": 0.0,
        "y": 0.0,
        "z": 0.0,
        "projection": None
    }

    def __init__(self, series, name=None, kind=None, settings=None,
                 metadata=None, **kwargs):
        """Class that supports or user-provided time series within PASTAS.

        Parameters
        ----------
        series: pandas.Series
            original series, which will be stored.
        name: str
            string with the name for this series.
        kind: str
            string with the kind of the series, to autocomplete the
            following keywords. The user can choose from: oseries, evap,
            prec, well.
        freq: str
            String containing the desired frequency. The required string format
             is found at http://pandas.pydata.org/pandas-docs/stable/timeseries.html#offset-aliases
        sample_up: optional: str or float
            Methods or float number to fill nan-values. Default values is
            'mean'. Currently supported options are: 'interpolate', float,
            and 'mean'. Interpolation is performed with a standard linear
            interpolation.
        sample_down: str or float
            method

        fill_before
        fill_after

        """
        pd.Series.__init__(self)
        if isinstance(series, TimeSeries):
            self.series_original = series.series_original
            self.freq_original = series.freq_original
            self.settings = series.settings
            self.metadata = series.metadata
            self.series = series.series
            self._update_inplace(series)

            validate = False
            update = False

            if kind is None:
                kind = series.kind
            # In the strange case somebody changes the kind after creation..
            elif kind is not series.kind:
                validate = True
                update = True
                series = series.series_original
        else:
            validate = True
            update = True
            # Store a copy of the original series
            self.series_original = series.copy()
            self.freq_original = None
            self.settings = dict(
                freq="D",
                sample_up=None,
                sample_down=None,
                fill_nan=None,
                fill_before=None,
                fill_after=None,
                tmin=None,
                tmax=None,
                norm=None
            )
            if kind in self._kind_settings.keys():
                self.settings.update(self._kind_settings[kind])

        # Use user provided name or set from series
        if name is None:
            name = series.name
        self.name = name

        # Options when creating the series
        self.kind = kind
        if metadata:
            self.metadata.update(metadata)

        # Update the options with user-provided values, if any.
        if settings:
            if self.update_settings(**settings):
                update = True
        if kwargs:
            if self.update_settings(**kwargs):
                update = True
        # Create a validated series for computations
        if validate:
            self.series = self.validate_series(series)

        if update:
            self.update_series(initial=True, **self.settings)

    def validate_series(self, series):
        """ This method performs some PASTAS specific tests for the TimeSeries.

        Parameters
        ----------
        series: pd.Series
            Pandas series object containing the series time series.

        Returns
        -------
        series: pandas.Series
            The validated series as pd.Series

        Notes
        -----
        The Series are validated for the following cases:

            1. Series is an actual pandas Series;
            2. Nan-values from begin and end are removed;
            3. Nan-values between observations are removed;
            4. Indices are in Timestamps (standard throughout PASTAS);
            5. Duplicate indices are removed (by averaging).

        """

        # 1. Check if series is a Pandas Series
        assert isinstance(series, pd.Series), 'Expected a Pandas Series, ' \
                                              'got %s' % type(series)

        # 4. Make sure the indices are Timestamps and sorted
        series.index = pd.to_datetime(series.index)
        series.sort_index(inplace=True)

        # 2. Drop nan-values at the beginning and end of the time series
        series = series.loc[series.first_valid_index():series.last_valid_index(
        )].copy(deep=True)

        # 3. Find the frequency of the original series
        freq = pd.infer_freq(series.index)

        if freq:
            self.freq_original = freq
            if not self.settings["freq"]:
                self.settings["freq"] = freq
            print('Inferred frequency from time series %s: freq=%s ' % (
                self.name, freq))
        else:
            self.freq_original = self.settings["freq"]
            if self.settings["fill_nan"] and self.settings["fill_nan"] != \
                    "drop":
                warn("User-provided frequency is applied when validating the "
                     "Time Series %s. Make sure the provided frequency is "
                     "close to the real frequency of the original series." %
                     (self.name))

        # 3. drop nan-values
        if series.hasnans:
            series = self.fill_nan(series)

        # 5. Handle duplicate indices
        if not series.index.is_unique:
            print('duplicate time-indexes were found in the Time Series %s. '
                  'Values were averaged.' % (self.name))
            grouped = series.groupby(level=0)
            series = grouped.mean()

        self.settings["tmin"] = series.index.min()
        self.settings["tmax"] = series.index.max()

        return series

    def update_settings(self, **kwargs):
        """Method that check if an update is actually necessary.

        TODO still some bug in here when comparing timestamps. causing uneccesary updates..

        """
        update = False
        for key, value in kwargs.items():
            if value != self.settings[key]:
                self.settings[key] = value
                update = True
        return update

    def update_series(self, initial=False, **kwargs):
        """Method to update the series with new options, but most likely
        only a change in the frequency before solving a PASTAS model.

        Parameters
        ----------
        kwargs: dict
            dictionary with the keyword arguments that are updated. Possible
            arguments are: "freq", "sample_up", "sample_down",
                 "fill_before" and "fill_after".

        """
        if self.update_settings(**kwargs) or initial:
            # Get the validated series to start with
            series = self.series.copy(deep=True)

            # Update the series with the new settings
            series = self.change_frequency(series)
            series = self.fill_before(series)
            series = self.fill_after(series)
            series = self.normalize(series)

            self._update_inplace(series)

    def change_frequency(self, series):
        """Method to change the frequency of the time series.

        """

        freq = self.settings["freq"]

        # 1. If no freq string is present or is provided (e.g. Oseries)
        if not freq:
            pass

        # 2. If new frequency is lower than its original.
        elif get_dt(freq) < get_dt(self.freq_original):
            series = self.sample_up(series)

        # 3. If new frequency is higher than its original, downsample.
        elif get_dt(freq) > get_dt(self.freq_original):
            series = self.sample_down(series)

        # 4. If new frequency is equal to its original.
        elif get_dt(freq) == get_dt(self.freq_original):
            series = self.fill_nan(series)
        else:
            series = self.series

        # Drop nan-values at the beginning and end of the time series
        series = series.loc[
                 series.first_valid_index():series.last_valid_index()]

        return series

    def sample_up(self, series):
        """Resample the time series when the frequency increases (e.g. from
        weekly to daily values).

        """
        method = self.settings["sample_up"]
        freq = self.settings["freq"]

        if method in ['backfill', 'bfill', 'pad', 'ffill']:
            series = series.asfreq(freq, method=method)
        elif method is None:
            pass
        else:
            series = series.asfreq(freq)
            if method == 'mean':
                series.fillna(series.mean(), inplace=True)  # Default option
            elif method == 'interpolate':
                series.interpolate(method='time', inplace=True)
            elif type(method) == float:
                series.fillna(method, inplace=True)
            else:
                warn('User-defined option for sample_up %s is not '
                     'supported' % method)

        print('%i nan-value(s) was/were found and filled with: %s'
              % (series.isnull().values.sum(), method))

        return series

    def sample_down(self, series):
        """Resample the time series when the frequency decreases (e.g. from
        daily to weekly values).

        Notes
        -----
        make sure the labels are still at the end of each period, and
        data at the right side of the bucket is included (see
        http://pandas.pydata.org/pandas-docs/stable/generated/pandas.Series.resample.html)

        """
        method = self.settings["sample_down"]
        freq = self.settings["freq"]

        # Provide some standard pandas arguments for all options
        kwargs = {"label": 'right', "closed": 'right'}

        if method == "mean":
            series = series.resample(freq, **kwargs).mean()
        elif method == "drop":
            series = series.resample(freq, **kwargs).dropna()
        elif method == "sum":
            series = series.resample(freq, **kwargs).sum()
        elif method == "min":
            series = series.resample(freq, **kwargs).min()
        elif method == "max":
            series = series.resample(freq, **kwargs).max()
        else:
            warn('User-defined option for sample_down %s is not '
                 'supported' % method)

        print("Time Series %s were sampled down to freq %s with method %s" %
              (self.name, freq, method))

        return series

    def fill_nan(self, series):
        """Fill up the nan-values when present and a constant frequency is
        required.

        """

        method = self.settings["fill_nan"]
        freq = self.freq_original

        if freq:
            series = series.asfreq(freq)

            if method == "drop":
                series.dropna(inplace=True)
            elif method == 'mean':
                series.fillna(series.mean(), inplace=True)  # Default option
            elif method == 'interpolate':
                series.interpolate(method='time', inplace=True)
            elif type(method) == float:
                series.fillna(method, inplace=True)
            else:
                warn('User-defined option for fill_nan %s is not '
                     'supported' % method)
        else:
            series.dropna(inplace=True)

        print('%i nan-value(s) was/were found and filled with: %s'
              % (series.isnull().values.sum(), method))

        return series

    def fill_before(self, series):
        """Method to add a period in front of the available time series.

        """

        freq = self.settings["freq"]
        method = self.settings["fill_before"]
        tmin = self.settings["tmin"]

        if tmin is None:
            pass
        elif pd.Timestamp(tmin) >= series.index.min():
            pass
        else:
            tmin = pd.Timestamp(tmin)
            # When time offsets are not equal
            time_offset = get_time_offset(tmin, freq)
            tmin = tmin - time_offset

            index_extend = pd.date_range(start=tmin, end=series.index.min(),
                                         freq=freq)
            index = series.index.union(index_extend[:-1])
            series = series.reindex(index)

            if method == 'mean':
                series.fillna(series.mean(), inplace=True)  # Default option
            elif type(method) == float:
                series.fillna(method, inplace=True)
            else:
                warn('User-defined option for sample_up %s is not '
                     'supported' % method)

        return series

    def fill_after(self, series):
        """Method to add a period in front of the available time series.

        """

        freq = self.settings["freq"]
        method = self.settings["fill_after"]
        tmax = self.settings["tmax"]

        if tmax is None:
            pass
        elif pd.Timestamp(tmax) <= series.index.max():
            pass
        elif method is None:
            pass
        else:
            # When time offsets are not equal
            time_offset = get_time_offset(tmax, freq)
            tmax = tmax - time_offset
            index_extend = pd.date_range(start=tmax, end=series.index.max(),
                                         freq=freq)
            index = self.index.union(index_extend[:-1])
            series = series.reindex(index)

            if method == 'mean':
                series.fillna(series.mean(), inplace=True)  # Default option
            elif type(method) == float:
                series.fillna(method, inplace=True)
            else:
                warn('User-defined option for fill_after %s is not '
                     'supported' % method)

        return series

    def normalize(self, series):
        """Method to normalize the time series,

        """

        method = self.settings["norm"]

        if method is None:
            pass
        elif method == "mean":
            series = series.subtract(series.mean())

        return series

    def dump(self, series=True, key=None):
        """Method to export the Time Series to a json format.

        Returns
        -------
        data: dict
            dictionary with the necessary information to recreate the
            TimeSeries object completely.

        """
        data = dict()

        if key is None:
            key = "series"

        if series:
            data[key] = self.series_original
        else:
            data[key] = self.name

        data["settings"] = self.settings
        data["kind"] = self.kind

        return data