
import re
import numpy as np
import logging
import warnings
from collections.abc import Iterable
import copy

from astropy.io import fits
from .utils import contiguous_regions, jit, HAS_NUMBA
from .utils import assign_value_if_none, apply_function_if_none
from .utils import check_iterables_close
from stingray.exceptions import StingrayError


__all__ = ['load_gtis', 'check_gtis',
           'create_gti_mask_jit', 'create_gti_mask',
           'create_gti_mask_complete', 'create_gti_from_condition',
           'cross_two_gtis', 'cross_gtis', 'get_btis',
           'get_gti_extensions_from_pattern', 'get_gti_from_all_extensions',
           'get_gti_from_hdu', 'get_gti_lengths', 'get_total_gti_length',
           'check_separate', 'append_gtis', 'join_gtis',
           'generate_indices_of_gti_boundaries',
           'time_intervals_from_gtis', 'bin_intervals_from_gtis',
           'gti_border_bins',
           'generate_indices_of_segment_boundaries_unbinned',
           'generate_indices_of_segment_boundaries_binned']


def gti_len(gti):
    """Deprecated, will be removed in version 2.0. Use get_total_gti_length."""
    warnings.warn("This function is deprecated. Use get_total_gti_length "\
                  "instead", DeprecationWarning)
    return get_total_gti_length(gti, minlen=0)


def get_gti_lengths(gti):
    """
    Calculate the length of each Good Time Interval.

    Parameters
    ----------
    gti : [[gti00, gti01], [gti10, gti11], ...]
        The list of good time intervals.

    Returns
    -------
    lengths : `np.ndarray`
        List of GTI lengths.

    Examples
    --------
    >>> gti = [[0, 1000], [1000, 1001], [3000, 3020]]
    >>> np.allclose(get_gti_lengths(gti), [1000, 1, 20])
    True
    """
    return np.diff(gti, axis=1).flatten()


def get_total_gti_length(gti, minlen=0):
    """
    Calculate the total exposure during Good Time Intervals.

    Parameters
    ----------
    gti : [[gti00, gti01], [gti10, gti11], ...]
        The list of good time intervals.
    minlen : float
        Minimum GTI length to consider.

    Returns
    -------
    length : float
        The total exposure during GTIs.

    Examples
    --------
    >>> gti = [[0, 1000], [1000, 1001], [3000, 3020]]
    >>> get_total_gti_length(gti)
    1021
    >>> get_total_gti_length(gti, minlen=5)
    1020
    """
    lengths = get_gti_lengths(gti)
    return np.sum(lengths[lengths >= minlen])


def load_gtis(fits_file, gtistring=None):
    """
    Load Good Time Intervals (GTIs) from ``HDU EVENTS`` of file ``fits_file``.
    File is expected to be in FITS format.

    Parameters
    ----------
    fits_file : str
        File name and path for the FITS file with the GTIs to be loaded.

    gtistring : str
        If the name of the FITS extension with the GTIs is not ``GTI``, the
        alternative name can be set with this parameter.

    Returns
    -------
    gti_list : list
        A list of GTI ``(start, stop)`` pairs extracted from the FITS file.
    """

    gtistring = assign_value_if_none(gtistring, 'GTI')
    logging.info("Loading GTIS from file %s" % fits_file)
    lchdulist = fits.open(fits_file, checksum=True, ignore_missing_end=True)
    lchdulist.verify('warn')

    gtitable = lchdulist[gtistring].data
    gti_list = np.array([[a, b]
                         for a, b in zip(gtitable.field('START'),
                                         gtitable.field('STOP'))],
                        dtype=np.longdouble)
    lchdulist.close()
    return gti_list


def get_gti_extensions_from_pattern(lchdulist, name_pattern="GTI"):
    """
    Gets the GTI extensions that match a given pattern.

    Parameters
    ----------
    lchdulist: `:class:astropy.io.fits.HDUList` object
        The full content of a FITS file.
    name_pattern: str
        Pattern indicating all the GTI extensions.

    Returns
    -------
    ext_list: list
        List of GTI extension numbers whose name matches the input pattern.

    Examples
    --------
    >>> from astropy.io import fits
    >>> start = np.arange(0, 300, 100)
    >>> stop = start + 50.
    >>> s1 = fits.Column(name='START', array=start, format='D')
    >>> s2 = fits.Column(name='STOP', array=stop, format='D')
    >>> hdu1 = fits.TableHDU.from_columns([s1, s2], name='GTI005XX')
    >>> hdu2 = fits.TableHDU.from_columns([s1, s2], name='GTI00501')
    >>> lchdulist = fits.HDUList([hdu1])
    >>> gtiextn = get_gti_extensions_from_pattern(
    ...     lchdulist, name_pattern='GTI005[0-9]+')
    >>> np.allclose(gtiextn, [1])
    True
    """
    hdunames = [h.name for h in lchdulist]
    pattern_re = re.compile("^" + name_pattern + "$")
    gtiextn = []
    for ix, extname in enumerate(hdunames):
        if pattern_re.match(extname):
            gtiextn.append(ix)
    return gtiextn


def hdu_contains_gti(hdu):
    """
    Test if a given FITS HDU contains a list of GTIs.

    Examples
    --------
    >>> from astropy.io import fits
    >>> start = np.arange(0, 300, 100)
    >>> stop = start + 50.
    >>> s1 = fits.Column(name='START', array=start, format='D')
    >>> s2 = fits.Column(name='STOP', array=stop, format='D')
    >>> hdu1 = fits.TableHDU.from_columns([s1, s2], name='BLABLA')
    >>> hdu_contains_gti(hdu1)
    True
    >>> s2 = fits.Column(name='blabla', array=stop, format='D')
    >>> hdu1 = fits.TableHDU.from_columns([s1, s2], name='BLABLA')
    >>> hdu_contains_gti(hdu1)
    False
    """
    colnames = [c.lower() for c in hdu.data.columns.names]
    return "start" in colnames and "stop" in colnames


def get_gti_from_hdu(gtihdu):
    """
    Get the GTIs from a given FITS extension.

    Parameters
    ----------
    gtihdu: `:class:astropy.io.fits.TableHDU` object
        The GTI HDU.

    Returns
    -------
    gti_list: [[gti00, gti01], [gti10, gti11], ...]
        List of good time intervals.

    Examples
    --------
    >>> from astropy.io import fits
    >>> start = np.arange(0, 300, 100)
    >>> stop = start + 50.
    >>> s1 = fits.Column(name='START', array=start, format='D')
    >>> s2 = fits.Column(name='STOP', array=stop, format='D')
    >>> hdu1 = fits.TableHDU.from_columns([s1, s2], name='GTI00501')
    >>> gti = get_gti_from_hdu(hdu1)
    >>> np.allclose(gti, [[0, 50], [100, 150], [200, 250]])
    True
    """
    gtitable = gtihdu.data

    colnames = [col.name for col in gtitable.columns]
    # Default: NuSTAR: START, STOP. Otherwise, try RXTE: Start, Stop
    if "START" in colnames:
        startstr, stopstr = "START", "STOP"
    else:
        startstr, stopstr = "Start", "Stop"

    gtistart = np.array(gtitable.field(startstr), dtype=np.longdouble)
    gtistop = np.array(gtitable.field(stopstr), dtype=np.longdouble)
    gti_list = np.vstack((gtistart, gtistop)).T

    return gti_list


def get_gti_from_all_extensions(lchdulist, accepted_gtistrings=["GTI"],
                                det_numbers=None):
    """
    Intersect the GTIs from the all accepted extensions.

    Parameters
    ----------
    lchdulist: `:class:astropy.io.fits.HDUList` object
        The full content of a FITS file.
    accepted_gtistrings: list of str
        Base strings of GTI extensions. For missions adding the detector number
        to GTI extensions like, e.g., XMM and Chandra, this function
        automatically adds the detector number and looks for all matching
        GTI extensions (e.g. "STDGTI" will also retrieve "STDGTI05"; "GTI0"
        will also retrieve "GTI00501").

    Returns
    -------
    gti_list: [[gti00, gti01], [gti10, gti11], ...]
        List of good time intervals, as the intersection of all matching GTIs.
        If there are two matching extensions, with GTIs [[0, 50], [100, 200]]
        and [[40, 70]] respectively, this function will return [[40, 50]].

    Examples
    --------
    >>> from astropy.io import fits
    >>> s1 = fits.Column(name='START', array=[0, 100, 200], format='D')
    >>> s2 = fits.Column(name='STOP', array=[50, 150, 250], format='D')
    >>> hdu1 = fits.TableHDU.from_columns([s1, s2], name='GTI00501')
    >>> s1 = fits.Column(name='START', array=[200, 300], format='D')
    >>> s2 = fits.Column(name='STOP', array=[250, 350], format='D')
    >>> hdu2 = fits.TableHDU.from_columns([s1, s2], name='STDGTI05')
    >>> lchdulist = fits.HDUList([hdu1, hdu2])
    >>> gti = get_gti_from_all_extensions(
    ...     lchdulist, accepted_gtistrings=['GTI0', 'STDGTI'],
    ...     det_numbers=[5])
    >>> np.allclose(gti, [[200, 250]])
    True
    """
    acc_gti_strs = copy.deepcopy(accepted_gtistrings)
    if det_numbers is not None:
        for i in det_numbers:
            acc_gti_strs += [
                x + "{:02d}".format(i) for x in accepted_gtistrings
            ]
            acc_gti_strs += [
                x + "{:02d}.*".format(i) for x in accepted_gtistrings
            ]
    gtiextn = []
    for pattern in acc_gti_strs:
        gtiextn.extend(get_gti_extensions_from_pattern(lchdulist, pattern))
    gtiextn = list(set(gtiextn))
    gti_lists = []
    for extn in gtiextn:
        gtihdu = lchdulist[extn]
        gti_lists.append(get_gti_from_hdu(gtihdu))
    return cross_gtis(gti_lists)


def check_gtis(gti):
    """
    Check if GTIs are well-behaved.

    Check that:

    1. the shape of the GTI array is correct;
    2. no start > end
    3. no overlaps.

    Parameters
    ----------
    gti : list
        A list of GTI ``(start, stop)`` pairs extracted from the FITS file.

    Raises
    ------
    TypeError
        If GTIs are of the wrong shape
    ValueError
        If GTIs have overlapping or displaced values
    """
    if len(gti) < 1:
        raise ValueError("Empty GTIs.")

    for g in gti:
        if np.size(g) != 2 or np.ndim(g) != 1:
            raise TypeError(
                "Please check the formatting of the GTIs. They need to be"
                " provided as [[gti00, gti01], [gti10, gti11], ...].")

    gti = np.array(gti)
    gti_start = gti[:, 0]
    gti_end = gti[:, 1]

    # Check that GTIs are well-behaved
    if not np.all(gti_end >= gti_start):
        raise ValueError('The GTI end times must be larger than the '
                         'GTI start times.')

    # Check that there are no overlaps in GTIs
    if not np.all(gti_start[1:] >= gti_end[:-1]):
        raise ValueError('This GTI has overlaps.')

    return


@jit(nopython=True)
def create_gti_mask_jit(time, gtis, mask, gti_mask,
                        min_length=0):  # pragma: no cover
    """
    Compiled and fast function to create GTI mask.

    Parameters
    ----------
    time : numpy.ndarray
        An array of time stamps

    gtis : iterable of ``(start, stop)`` pairs
        The list of GTIs.

    mask : numpy.ndarray
        A pre-assigned array of zeros of the same shape as ``time``
        Records whether a time stamp is part of the GTIs.

    gti_mask : numpy.ndarray
        A pre-assigned array zeros in the same shape as ``time``; records
        start/stop of GTIs.

    min_length : float
        An optional minimum length for the GTIs to be applied. Only GTIs longer
        than ``min_length`` will be considered when creating the mask.

    """
    gti_el = -1
    next_gti = False
    for i, t in enumerate(time):
        if i == 0 or t > gtis[gti_el, 1] or next_gti:
            gti_el += 1
            if gti_el == len(gtis):
                break
            limmin = gtis[gti_el, 0]
            limmax = gtis[gti_el, 1]
            length = limmax - limmin
            if length < min_length:
                next_gti = True
                continue
            next_gti = False
            gti_mask[gti_el] = True

        if t < limmin:
            continue

        if t >= limmin:
            if t <= limmax:
                mask[i] = 1

    return mask, gti_mask


def create_gti_mask(time, gtis, safe_interval=None, min_length=0,
                    return_new_gtis=False, dt=None, epsilon=0.001):
    """
    Create GTI mask.

    Assumes that no overlaps are present between GTIs

    Parameters
    ----------
    time : numpy.ndarray
        An array of time stamps

    gtis : ``[[g0_0, g0_1], [g1_0, g1_1], ...]``, float array-like
        The list of GTIs


    Other parameters
    ----------------
    safe_interval : float or ``[float, float]``, default None
        A safe interval to exclude at both ends (if single float) or the start
        and the end (if pair of values) of GTIs. If None, no safe interval
        is applied to data.

    min_length : float
        An optional minimum length for the GTIs to be applied. Only GTIs longer
        than ``min_length`` will be considered when creating the mask.

    return_new_gtis : bool
        If ``True```, return the list of new GTIs (if ``min_length > 0``)

    dt : float
        Time resolution of the data, i.e. the interval between time stamps.

    epsilon : float
        Fraction of ``dt`` that is tolerated at the borders of a GTI.

    Returns
    -------
    mask : bool array
        A mask labelling all time stamps that are included in the GTIs versus
        those that are not.

    new_gtis : ``Nx2`` array
        An array of new GTIs created by this function.
    """
    gtis = np.array(gtis, dtype=np.longdouble)
    if time.size == 0:
        raise ValueError("Passing an empty time array to create_gti_mask")
    if gtis.size == 0:
        raise ValueError("Passing an empty GTI array to create_gti_mask")

    mask = np.zeros(len(time), dtype=bool)

    if min_length > 0:
        lengths = gtis[:, 1] - gtis[:, 0]
        good = lengths >= np.max(min_length, dt)
        if np.all(~good):
            warnings.warn("No GTIs longer than "
                          "min_length {}".format(min_length))
            return mask
        gtis = gtis[good]

    if not HAS_NUMBA:
        return create_gti_mask_complete(time, gtis,
                                        safe_interval=safe_interval,
                                        min_length=min_length,
                                        return_new_gtis=return_new_gtis,
                                        dt=dt, epsilon=epsilon)

    check_gtis(gtis)

    dt = apply_function_if_none(dt, time,
                                lambda x: np.median(np.diff(x)))
    epsilon_times_dt = epsilon * dt
    gtis_new = copy.deepcopy(gtis)
    gti_mask = np.zeros(len(gtis), dtype=bool)

    if safe_interval is not None:
        if not isinstance(safe_interval, Iterable):
            safe_interval = np.array([safe_interval, safe_interval])
        # These are the gtis that will be returned (filtered!). They are only
        # modified by the safe intervals
        gtis_new[:, 0] = gtis[:, 0] + safe_interval[0]
        gtis_new[:, 1] = gtis[:, 1] - safe_interval[1]

    # These are false gtis, they contain a few boundary modifications
    # in order to simplify the calculation of the mask, but they will _not_
    # be returned.
    gtis_to_mask = copy.deepcopy(gtis_new)
    gtis_to_mask[:, 0] = gtis_new[:, 0] - epsilon_times_dt + dt / 2
    gtis_to_mask[:, 1] = gtis_new[:, 1] + epsilon_times_dt - dt / 2

    mask, gtimask = \
        create_gti_mask_jit((time - time[0]).astype(np.float64),
                            (gtis_to_mask - time[0]).astype(np.float64),
                            mask, gti_mask=gti_mask,
                            min_length=float(
            min_length - 2 * (1 + epsilon) * dt
        ))

    if return_new_gtis:
        return mask, gtis_new[gtimask]

    return mask


def create_gti_mask_complete(time, gtis, safe_interval=0, min_length=0,
                             return_new_gtis=False, dt=None, epsilon=0.001):
    """
    Create GTI mask, allowing for non-constant ``dt``.

    Assumes that no overlaps are present between GTIs.

    Parameters
    ----------
    time : numpy.ndarray
        An array of time stamps.

    gtis : ``[[g0_0, g0_1], [g1_0, g1_1], ...]``, float array-like
        The list of GTIs.


    Other parameters
    ----------------
    safe_interval : float or [float, float]
        A safe interval to exclude at both ends (if single float) or the start
        and the end (if pair of values) of GTIs.

    min_length : float
        An optional minimum length for the GTIs to be applied. Only GTIs longer
        than ``min_length`` will be considered when creating the mask.

    return_new_gtis : bool
        If ``True``, return the list of new GTIs (if ``min_length > 0``).

    dt : float
        Time resolution of the data, i.e. the interval between time stamps.

    epsilon : float
        Fraction of ``dt`` that is tolerated at the borders of a GTI.

    Returns
    -------
    mask : bool array
        A mask labelling all time stamps that are included in the GTIs versus
        those that are not.

    new_gtis : Nx2 array
        An array of new GTIs created by this function.
    """

    check_gtis(gtis)

    dt = assign_value_if_none(dt,
                              np.zeros_like(time) +
                              np.median(np.diff(np.sort(time)) / 2))

    epsilon_times_dt = epsilon * dt
    mask = np.zeros(len(time), dtype=bool)

    if safe_interval is None:
        safe_interval = [0, 0]
    elif not isinstance(safe_interval, Iterable):
        safe_interval = [safe_interval, safe_interval]

    newgtis = np.zeros_like(gtis)
    # Whose GTIs, including safe intervals, are longer than min_length
    newgtimask = np.zeros(len(newgtis), dtype=bool)

    for ig, gti in enumerate(gtis):
        limmin, limmax = gti
        limmin += safe_interval[0]
        limmax -= safe_interval[1]
        if limmax - limmin >= min_length:
            newgtis[ig][:] = [limmin, limmax]
            cond1 = time >= (limmin + dt / 2 - epsilon_times_dt)
            cond2 = time <= (limmax - dt / 2 + epsilon_times_dt)

            good = np.logical_and(cond1, cond2)
            mask[good] = True
            newgtimask[ig] = True

    res = mask
    if return_new_gtis:
        res = [res, newgtis[newgtimask]]
    return res


def create_gti_from_condition(time, condition,
                              safe_interval=0, dt=None):
    """
    Create a GTI list from a time array and a boolean mask (``condition``).

    Parameters
    ----------
    time : array-like
        Array containing time stamps.

    condition : array-like
        An array of bools, of the same length of time.
        A possible condition can be, e.g., the result of ``lc > 0``.

    Returns
    -------
    gtis : ``[[gti0_0, gti0_1], [gti1_0, gti1_1], ...]``
        The newly created GTIs.

    Other parameters
    ----------------
    safe_interval : float or ``[float, float]``
        A safe interval to exclude at both ends (if single float) or the start
        and the end (if pair of values) of GTIs.
    dt : float
        The width (in sec) of each bin of the time array. Can be irregular.
    """

    if len(time) != len(condition):
        raise StingrayError('The length of the condition and '
                            'time arrays must be the same.')

    idxs = contiguous_regions(condition)

    if not isinstance(safe_interval, Iterable):
        safe_interval = [safe_interval, safe_interval]

    dt = assign_value_if_none(dt,
                              np.zeros_like(time) + (time[1] - time[0]) / 2)

    gtis = []
    for idx in idxs:
        logging.debug(idx)
        startidx = idx[0]
        stopidx = idx[1] - 1

        t0 = time[startidx] - dt[startidx] + safe_interval[0]
        t1 = time[stopidx] + dt[stopidx] - safe_interval[1]
        if t1 - t0 < 0:
            continue
        gtis.append([t0, t1])
    return np.array(gtis)


def cross_two_gtis(gti0, gti1):
    """
    Extract the common intervals from two GTI lists *EXACTLY*.

    Parameters
    ----------
    gti0 : iterable of the form ``[[gti0_0, gti0_1], [gti1_0, gti1_1], ...]``
    gti1 : iterable of the form ``[[gti0_0, gti0_1], [gti1_0, gti1_1], ...]``
        The two lists of GTIs to be crossed.

    Returns
    -------
    gtis : ``[[gti0_0, gti0_1], [gti1_0, gti1_1], ...]``
        The newly created GTIs.

    See Also
    --------
    cross_gtis : From multiple GTI lists, extract common intervals *EXACTLY*

    Examples
    --------
    >>> gti1 = np.array([[1, 2]])
    >>> gti2 = np.array([[1, 2]])
    >>> newgti = cross_two_gtis(gti1, gti2)
    >>> np.allclose(newgti, [[1, 2]])
    True
    >>> gti1 = np.array([[1, 4]])
    >>> gti2 = np.array([[1, 2], [2, 4]])
    >>> newgti = cross_two_gtis(gti1, gti2)
    >>> np.allclose(newgti, [[1, 4]])
    True
    """
    gti0 = join_equal_gti_boundaries(np.asarray(gti0))
    gti1 = join_equal_gti_boundaries(np.asarray(gti1))
    # Check GTIs
    check_gtis(gti0)
    check_gtis(gti1)

    gti0_start = gti0[:, 0]
    gti0_end = gti0[:, 1]
    gti1_start = gti1[:, 0]
    gti1_end = gti1[:, 1]

    # Create a list that references to the two start and end series
    gti_start = [gti0_start, gti1_start]
    gti_end = [gti0_end, gti1_end]

    # Concatenate the series, while keeping track of the correct origin of
    # each start and end time
    gti0_tag = np.array([0 for g in gti0_start], dtype=bool)
    gti1_tag = np.array([1 for g in gti1_start], dtype=bool)
    conc_start = np.concatenate((gti0_start, gti1_start))
    conc_end = np.concatenate((gti0_end, gti1_end))
    conc_tag = np.concatenate((gti0_tag, gti1_tag))

    # Put in time order
    order = np.argsort(conc_end)
    conc_start = conc_start[order]
    conc_end = conc_end[order]
    conc_tag = conc_tag[order]

    last_end = conc_start[0] - 1
    final_gti = []
    for ie, e in enumerate(conc_end):
        # Is this ending in series 0 or 1?
        this_series = int(conc_tag[ie])
        other_series = int(this_series == 0)

        # Check that this closes intervals in both series.
        # 1. Check that there is an opening in both series 0 and 1 lower than e
        try:
            st_pos = \
                np.argmax(gti_start[this_series][gti_start[this_series] < e])
            so_pos = \
                np.argmax(gti_start[other_series][gti_start[other_series] < e])
            st = gti_start[this_series][st_pos]
            so = gti_start[other_series][so_pos]

            s = np.max([st, so])
        except:  # pragma: no cover
            continue

        # If this start is inside the last interval (It can happen for equal
        # GTI start times between the two series), then skip!
        if s <= last_end:
            continue
        # 2. Check that there is no closing before e in the "other series",
        # from intervals starting either after s, or starting and ending
        # between the last closed interval and this one
        cond1 = (gti_end[other_series] > s) * (gti_end[other_series] < e)
        cond2 = gti_end[other_series][so_pos] < s
        condition = np.any(np.logical_or(cond1, cond2))
        # Well, if none of the conditions at point 2 apply, then you can
        # create the new gti!
        if not condition:
            final_gti.append([s, e])
            last_end = e

    return np.array(final_gti)


def cross_gtis(gti_list):
    """
    From multiple GTI lists, extract the common intervals *EXACTLY*.

    Parameters
    ----------
    gti_list : array-like
        List of GTI arrays, each one in the usual format
        ``[[gti0_0, gti0_1], [gti1_0, gti1_1], ...]``.

    Returns
    -------
    gti0: 2-d float array
        ``[[gti0_0, gti0_1], [gti1_0, gti1_1], ...]``
        The newly created GTIs.

    See Also
    --------
    cross_two_gtis : Extract the common intervals from two GTI lists *EXACTLY*

    Examples
    --------
    >>> gti1 = np.array([[1, 2]])
    >>> gti2 = np.array([[1, 2]])
    >>> newgti = cross_gtis([gti1, gti2])
    >>> np.allclose(newgti, [[1, 2]])
    True
    >>> gti1 = np.array([[1, 4]])
    >>> gti2 = np.array([[1, 2], [2, 4]])
    >>> newgti = cross_gtis([gti1, gti2])
    >>> np.allclose(newgti, [[1, 4]])
    True
    """
    for g in gti_list:
        check_gtis(g)

    ninst = len(gti_list)
    if ninst == 1:
        return gti_list[0]

    gti0 = gti_list[0]

    for gti in gti_list[1:]:
        gti0 = cross_two_gtis(gti0, gti)

    return gti0


def get_btis(gtis, start_time=None, stop_time=None):
    """
    From GTIs, obtain bad time intervals, i.e. the intervals *not* covered
    by the GTIs.

    GTIs have to be well-behaved, in the sense that they have to pass
    ``check_gtis``.

    Parameters
    ----------
    gtis : iterable
        A list of GTIs.

    start_time : float
        Optional start time of the overall observation (e.g. can be earlier
        than the first time stamp in ``gtis``).

    stop_time : float
        Optional stop time of the overall observation (e.g. can be later than
        the last time stamp in``gtis``).

    Returns
    -------
    btis : numpy.ndarray
        A list of bad time intervals.
    """
    # Check GTIs
    if len(gtis) == 0:
        if start_time is None or stop_time is None:
            raise ValueError('Empty GTI and no valid start_time '
                             'and stop_time. BAD!')

        return np.asarray([[start_time, stop_time]])
    check_gtis(gtis)

    start_time = assign_value_if_none(start_time, gtis[0][0])
    stop_time = assign_value_if_none(stop_time, gtis[-1][1])

    if gtis[0][0] <= start_time:
        btis = []
    else:
        btis = [[start_time, gtis[0][0]]]
    # Transform GTI list in
    flat_gtis = gtis.flatten()
    new_flat_btis = zip(flat_gtis[1:-2:2], flat_gtis[2:-1:2])
    btis.extend(new_flat_btis)

    if stop_time > gtis[-1][1]:
        btis.extend([[gtis[-1][1],  stop_time]])

    return np.asarray(btis)


@jit(nopython=True)
def _check_separate(gti0, gti1):
    """Numba-compiled core of ``check_separate``."""
    gti0_start = gti0[:, 0]
    gti0_end = gti0[:, 1]
    gti1_start = gti1[:, 0]
    gti1_end = gti1[:, 1]

    if (gti0_end[-1] <= gti1_start[0]) or (gti1_end[-1] <= gti0_start[0]):
        return True

    for g in gti1.flatten():
        for g0, g1 in zip(gti0[:, 0], gti0[:, 1]):
            if (g <= g1) and (g >= g0):
                return False
    for g in gti0.flatten():
        for g0, g1 in zip(gti1[:, 0], gti1[:, 1]):
            if (g <= g1) and (g >= g0):
                return False
    return True


def check_separate(gti0, gti1):
    """
    Check if two GTIs do not overlap.

    Parameters
    ----------
    gti0: 2-d float array
        List of GTIs of form ``[[gti0_0, gti0_1], [gti1_0, gti1_1], ...]``.

    gti1: 2-d float array
        List of GTIs of form ``[[gti0_0, gti0_1], [gti1_0, gti1_1], ...]``.

    Returns
    -------
    separate: bool
        ``True`` if GTIs are mutually exclusive, ``False`` if not.

    Examples
    --------
    >>> gti0 = [[0, 10]]
    >>> gti1 = [[20, 30]]
    >>> check_separate(gti0, gti1)
    True
    >>> gti0 = [[0, 10]]
    >>> gti1 = [[0, 10]]
    >>> check_separate(gti0, gti1)
    False
    >>> gti0 = [[0, 10]]
    >>> gti1 = [[10, 20]]
    >>> check_separate(gti0, gti1)
    True
    >>> gti0 = [[0, 11]]
    >>> gti1 = [[10, 20]]
    >>> check_separate(gti0, gti1)
    False
    >>> gti0 = [[0, 11]]
    >>> gti1 = [[10, 20]]
    >>> check_separate(gti1, gti0)
    False
    >>> gti0 = [[0, 10], [30, 40]]
    >>> gti1 = [[11, 28]]
    >>> check_separate(gti0, gti1)
    True
    """

    gti0 = np.asarray(gti0)
    gti1 = np.asarray(gti1)
    if len(gti0) == 0 or len(gti1) == 0:
        return True

    # Check if independently GTIs are well behaved
    check_gtis(gti0)
    check_gtis(gti1)
    t0 = min(gti0[0, 0], gti1[0, 0])
    return _check_separate((gti0 - t0).astype(np.double),
                           (gti1 - t0).astype(np.double))


def join_equal_gti_boundaries(gti):
    """
    If the start of a GTI is right at the end of another, join them.
    """
    new_gtis = []
    for l in gti:
        new_gtis.append(l)
    touching = gti[:-1, 1] == gti[1:, 0]
    ng = []
    count = 0
    while count < len(gti)-1:
        if touching[count]:
            new_gtis[count+1] = [new_gtis[count][0], new_gtis[count+1][1]]
        else:
            ng.append(new_gtis[count])
        count += 1
    ng.append(new_gtis[-1])
    return np.asarray(ng)


def append_gtis(gti0, gti1):
    """
    Union of two non-overlapping GTIs.

    If the two GTIs "touch", this is tolerated and the touching GTIs are
    joined in a single one.

    Parameters
    ----------
    gti0: 2-d float array
        List of GTIs of the form ``[[gti0_0, gti0_1], [gti1_0, gti1_1], ...]``.

    gti1: 2-d float array
        List of GTIs of the form ``[[gti0_0, gti0_1], [gti1_0, gti1_1], ...]``.

    Returns
    -------
    gti: 2-d float array
        The newly created GTI array.

    Examples
    --------
    >>> np.allclose(append_gtis([[0, 1]], [[2, 3]]), [[0, 1], [2, 3]])
    True
    >>> np.allclose(append_gtis([[0, 1], [4, 5]], [[2, 3]]),
    ...             [[0, 1], [2, 3], [4, 5]])
    True
    >>> np.allclose(append_gtis([[0, 1]], [[1, 3]]), [[0, 3]])
    True
    """

    gti0 = np.asarray(gti0)
    gti1 = np.asarray(gti1)
    # Check if independently GTIs are well behaved.
    check_gtis(gti0)
    check_gtis(gti1)

    # Check if GTIs are mutually exclusive.
    if not check_separate(gti0, gti1):
        raise ValueError('In order to append, GTIs must be mutually'
                         'exclusive.')

    new_gtis = np.concatenate([gti0, gti1])
    order = np.argsort(new_gtis[:, 0])
    return join_equal_gti_boundaries(new_gtis[order])


def join_gtis(gti0, gti1):
    """
    Union of two GTIs.

    If GTIs are mutually exclusive, it calls ``append_gtis``. Otherwise we put
    the extremes of partially overlapping GTIs on an ideal line and look at the
    number of opened and closed intervals. When the number of closed and opened
    intervals is the same, the full GTI is complete and we close it.

    In practice, we assign to each opening time of a GTI the value ``-1``, and
    the value ``1`` to each closing time; when the cumulative sum is zero, the
    GTI has ended. The timestamp after each closed GTI is the start of a new
    one.

    ::

        (cumsum)   -1   -2         -1   0   -1 -2           -1  -2  -1        0
        GTI A      |-----:----------|   :    |--:------------|   |---:--------|
        FINAL GTI  |-----:--------------|    |--:--------------------:--------|
        GTI B            |--------------|       |--------------------|

    Parameters
    ----------
    gti0: 2-d float array
        List of GTIs of the form ``[[gti0_0, gti0_1], [gti1_0, gti1_1], ...]``

    gti1: 2-d float array
        List of GTIs of the form ``[[gti0_0, gti0_1], [gti1_0, gti1_1], ...]``

    Returns
    -------
    gti: 2-d float array
        The newly created GTI
    """

    gti0 = np.asarray(gti0)
    gti1 = np.asarray(gti1)

    # Check if independently GTIs are well behaved.
    check_gtis(gti0)
    check_gtis(gti1)

    if check_separate(gti0, gti1):
        return append_gtis(gti0, gti1)

    g0 = gti0.flatten()
    # Opening GTI: type = 1; Closing: type = -1
    g0_type = np.asarray(list(zip(-np.ones(int(len(g0) / 2)),
                                  np.ones(int(len(g0) / 2)))))
    g1 = gti1.flatten()
    g1_type = np.asarray(list(zip(-np.ones(int(len(g1) / 2)),
                                  np.ones(int(len(g1) / 2)))))

    g_all = np.append(g0, g1)
    g_type_all = np.append(g0_type, g1_type)
    order = np.argsort(g_all)
    g_all = g_all[order]
    g_type_all = g_type_all[order]

    sums = np.cumsum(g_type_all)

    # Where the cumulative sum is zero, we close the GTI
    closing_bins = sums == 0
    # The next element in the sequence is the start of the new GTI. In the case
    # of the last element, the next is the first. Numpy.roll gives this for
    # free.
    starting_bins = np.roll(closing_bins, 1)

    starting_times = g_all[starting_bins]
    closing_times = g_all[closing_bins]

    final_gti = []
    for start, stop in zip(starting_times, closing_times):
        final_gti.append([start, stop])

    return np.sort(final_gti, axis=0)


def time_intervals_from_gtis(gtis, segment_size, fraction_step=1,
                             epsilon=1e-5):
    """
    Compute start/stop times of equal time intervals, compatible with GTIs.

    Used to start each FFT/PDS/cospectrum from the start of a GTI,
    and stop before the next gap in data (end of GTI).

    Parameters
    ----------
    gtis : 2-d float array
        List of GTIs of the form ``[[gti0_0, gti0_1], [gti1_0, gti1_1], ...]``

    segment_size : float
        Length of the time segments

    fraction_step : float
        If the step is not a full ``segment_size`` but less (e.g. a moving
        window), this indicates the ratio between step step and
        ``segment_size`` (e.g. ``0.5`` means that the window shifts by half
        ``segment_size``).

    Returns
    -------
    spectrum_start_times : array-like
        List of starting times to use in the spectral calculations.

    spectrum_stop_times : array-like
        List of end times to use in the spectral calculations.

    """
    spectrum_start_times = np.array([], dtype=np.longdouble)
    for g in gtis:
        if g[1] - g[0] + epsilon < segment_size:
            continue

        newtimes = np.arange(g[0], g[1] - segment_size + epsilon,
                             np.longdouble(segment_size) * fraction_step,
                             dtype=np.longdouble)
        spectrum_start_times = \
            np.append(spectrum_start_times,
                      newtimes)

    assert len(spectrum_start_times) > 0, \
        ("No GTIs are equal to or longer than segment_size.")
    return spectrum_start_times, spectrum_start_times + segment_size


def calculate_segment_bin_start(startbin, stopbin, nbin, fraction_step=1):
    """Get the starting indices of intervals of equal length.

    A bit like `np.arange`, but checks that the last number is
    at least ``nbin`` less than ``stopbin``. Useful when getting
    starting intervals of equal chunks of a binned light curve.

    It is possible to make these intervals sliding, through the
    ``fraction_step`` parameter.

    Parameters
    ----------
    startbin : int
        Starting bin of the interval.

    stopbin : int
        Last bin of the interval.

    nbin : int
        Number of bins in each interval.

    Other Parameters
    ----------------
    fraction_step : float
        If the step is not a full ``nbin`` but less (e.g. a moving window),
        this indicates the ratio between the step and ``nbin`` (e.g.
        ``0.5`` means that the window shifts by half ``nbin``).

    Returns
    -------
    spectrum_start_bins : array-like
        List of starting bins in the original time array to use in spectral
        calculations.

    Examples
    --------
    >>> st = calculate_segment_bin_start(0, 10000, 10000)
    >>> st[-1]
    0
    >>> st = calculate_segment_bin_start(0, 5, 2)
    >>> st[-1]
    2
    >>> st = calculate_segment_bin_start(0, 6, 2)
    >>> st[-1]
    4
    """
    st = np.arange(startbin, stopbin, int(nbin * fraction_step), dtype=int)
    if st[-1] + nbin > stopbin:
        return st[:-1]
    return st


def bin_intervals_from_gtis(gtis, segment_size, time, dt=None, fraction_step=1,
                            epsilon=0.001):
    """
    Compute start/stop times of equal time intervals, compatible with GTIs,
    and map them to the indices of an array of time stamps.

    Used to start each FFT/PDS/cospectrum from the start of a GTI,
    and stop before the next gap in data (end of GTI).
    In this case, it is necessary to specify the time array containing the
    times of the light curve bins.
    Returns start and stop bins of the intervals to use for the PDS.

    Parameters
    ----------
    gtis : 2-d float array
        List of GTIs of the form ``[[gti0_0, gti0_1], [gti1_0, gti1_1], ...]``.

    segment_size : float
        Length of each time segment.

    time : array-like
        Array of time stamps.

    Other Parameters
    ----------------
    dt : float, default median(diff(time))
        Time resolution of the light curve.

    epsilon : float, default 0.001
        The tolerance, in fraction of ``dt``, for the comparisons at the
        borders.

    fraction_step : float
        If the step is not a full ``segment_size`` but less (e.g. a moving
        window), this indicates the ratio between step step and
        ``segment_size`` (e.g. ``0.5`` means that the window shifts by half
        ``segment_size``).

    Returns
    -------
    spectrum_start_bins : array-like
        List of starting bins in the original time array to use in spectral
        calculations.

    spectrum_stop_bins : array-like
        List of end bins to use in the spectral calculations.

    Examples
    --------
    >>> time = np.arange(0.5, 13.5)

    >>> gtis = [[0, 5], [6, 8], [9, 10]]

    >>> segment_size = 2

    >>> start_bins, stop_bins = bin_intervals_from_gtis(gtis,segment_size,time)

    >>> np.allclose(start_bins, [0, 2, 6])
    True
    >>> np.allclose(stop_bins, [2, 4, 8])
    True
    >>> np.allclose(time[start_bins[0]:stop_bins[0]], [0.5, 1.5])
    True
    >>> np.allclose(time[start_bins[1]:stop_bins[1]], [2.5, 3.5])
    True
    """
    time = np.asarray(time)
    gtis = np.asarray(gtis)
    if dt is None:
        dt = np.median(np.diff(time))

    epsilon_times_dt = epsilon * dt
    nbin = np.rint(segment_size / dt).astype(int)

    if time[-1] < np.min(gtis) or time[0] > np.max(gtis):
        raise ValueError("Invalid time interval for the given GTIs")

    spectrum_start_bins = np.array([], dtype=int)

    gti_low = gtis[:, 0] + dt / 2 - epsilon_times_dt
    gti_up = gtis[:, 1] - dt / 2 + epsilon_times_dt

    for g0, g1 in zip(gti_low, gti_up):
        if (g1 - g0 + dt + epsilon_times_dt) < segment_size:
            continue
        startbin, stopbin = np.searchsorted(time, [g0, g1], "left")
        stopbin += 1
        if stopbin > time.size:
            stopbin = time.size

        if time[startbin] < g0:
            startbin += 1
        # Would be g[1] - dt/2, but stopbin is the end of an interval
        # so one has to add one bin
        if time[stopbin - 1] > g1:
            stopbin -= 1

        newbins = calculate_segment_bin_start(
            startbin, stopbin, nbin, fraction_step=fraction_step)
        spectrum_start_bins = \
            np.append(spectrum_start_bins,
                      newbins)
    assert len(spectrum_start_bins) > 0, \
        ("No GTIs are equal to or longer than segment_size.")
    return spectrum_start_bins, spectrum_start_bins + nbin


def gti_border_bins(gtis, time, dt=None, epsilon=0.001):
    """
    Find the indices in a time array corresponding to the borders of GTIs.

    GTIs shorter than the bin time are not returned.

    Parameters
    ----------
    gtis : 2-d float array
        List of GTIs of the form ``[[gti0_0, gti0_1], [gti1_0, gti1_1], ...]``.

    time : array-like
        Array of time stamps.

    Other Parameters
    ----------------
    dt : float, default median(diff(time))
        Time resolution of the light curve.

    epsilon : float, default 0.001
        The tolerance, in fraction of ``dt``, for the comparisons at the
        borders.

    fraction_step : float
        If the step is not a full ``segment_size`` but less (e.g. a moving
        window), this indicates the ratio between step step and
        ``segment_size`` (e.g. ``0.5`` means that the window shifts by half
        ``segment_size``).

    Returns
    -------
    spectrum_start_bins : array-like
        List of starting bins of each GTI

    spectrum_stop_bins : array-like
        List of stop bins of each GTI. The elements corresponding to these bins
        should *not* be included.

    Examples
    --------
    >>> times = np.arange(0.5, 13.5)

    >>> gti_border_bins([[16., 18.]], times)
    Traceback (most recent call last):
        ...
    ValueError: Invalid time interval for the given GTIs

    >>> start_bins, stop_bins = gti_border_bins(
    ...    [[0, 5], [6, 8]], times)

    >>> np.allclose(start_bins, [0, 6])
    True
    >>> np.allclose(stop_bins, [5, 8])
    True
    >>> np.allclose(times[start_bins[0]:stop_bins[0]], [0.5, 1.5, 2.5, 3.5, 4.5])
    True
    >>> np.allclose(times[start_bins[1]:stop_bins[1]], [6.5, 7.5])
    True
    """
    time = np.asarray(time)
    gtis = np.asarray(gtis)
    if dt is None:
        dt = np.median(np.diff(time))

    epsilon_times_dt = epsilon * dt

    if time[-1] < np.min(gtis) or time[0] > np.max(gtis):
        raise ValueError("Invalid time interval for the given GTIs")

    spectrum_start_bins = []
    spectrum_stop_bins = []

    gti_low = gtis[:, 0] + dt / 2 - epsilon_times_dt
    gti_up = gtis[:, 1] - dt / 2 + epsilon_times_dt

    for g0, g1 in zip(gti_low, gti_up):
        startbin, stopbin = np.searchsorted(time, [g0, g1], "left")
        stopbin += 1
        if stopbin > time.size:
            stopbin = time.size

        if time[startbin] < g0:
            startbin += 1
        # Would be g[1] - dt/2, but stopbin is the end of an interval
        # so one has to add one bin
        if time[stopbin - 1] > g1:
            stopbin -= 1

        spectrum_start_bins.append(startbin)
        spectrum_stop_bins.append(stopbin)

    return np.array(spectrum_start_bins), np.array(spectrum_stop_bins)


def generate_indices_of_boundaries(times, gti, segment_size=None, dt=0):
    """
    Get index boundaries and times from different parts of the observation.

    It wraps around `generate_indices_of_gti_boundaries`,
    `generate_indices_of_segment_boundaries_binned`, and
    `generate_indices_of_segment_boundaries_unbinned` depending on:

    + ``segment_size`` being ``None`` (give GTI boundaries, segment boundaries
      otherwise)
    + ``dt`` being 0 or nonzero (unevenly sampled, evenly sampled otherwise)

    Examples
    --------
    >>> times = [0.1, 0.2, 0.5, 0.8, 1.1]
    >>> gtis = [[0, 0.55], [0.6, 2.1]]
    >>> vals0 = generate_indices_of_boundaries(times, gtis, segment_size=None)
    >>> vals1 = generate_indices_of_gti_boundaries(times, gtis)
    >>> check_iterables_close(vals0, vals1)
    True
    >>> vals0 = generate_indices_of_boundaries(times, gtis, segment_size=0.5)
    >>> vals1 = generate_indices_of_segment_boundaries_unbinned(times, gtis, segment_size=0.5)
    >>> check_iterables_close(vals0, vals1)
    True
    >>> times = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]
    >>> gtis = [[0.05, 0.55]]
    >>> vals0 = generate_indices_of_boundaries(times, gtis, segment_size=0.5, dt=0.1)
    >>> vals1 = generate_indices_of_segment_boundaries_binned(times, gtis, 0.5, dt=0.1)
    >>> check_iterables_close(vals0, vals1)
    True
    """
    if segment_size is not None:
        if dt is None or dt == 0:
            segment_iter = generate_indices_of_segment_boundaries_unbinned(
                times, gti, segment_size)
        else:
            segment_iter = generate_indices_of_segment_boundaries_binned(
                times, gti, segment_size, dt=dt)
    else:
        segment_iter = generate_indices_of_gti_boundaries(times, gti, dt=0)
    return segment_iter


def generate_indices_of_gti_boundaries(times, gti, dt=0):
    """
    Get the indices of events from different GTIs of the observation.

    This is a generator, yielding the boundaries of each GTI and the
    corresponding indices in the time array.

    Parameters
    ----------
    times : float `np.array`
        Array of times.
    gti : [[gti00, gti01], [gti10, gti11], ...]
        Good time intervals.

    Other parameters
    ----------------
    dt : float
        If times are uniformly binned, this is the binning time.

    Yields
    -------
    g0: float
        Start time of current GTI.
    g1: float
        End time of current GTI.
    startidx: int
        Start index of the current GTI in the time array.
    stopidx: int
        End index of the current GTI in the time array. Note that this is
        larger by one, so that `time[startidx:stopidx]` returns the correct
        time interval.

    Examples
    --------
    >>> times = [0.1, 0.2, 0.5, 0.8, 1.1]
    >>> gtis = [[0, 0.55], [0.6, 2.1]]
    >>> vals = generate_indices_of_gti_boundaries(times, gtis)
    >>> v0 = next(vals)
    >>> np.allclose(v0[:2], gtis[0])
    True
    >>> np.allclose(v0[2:], [0, 3])
    True
    """
    gti = np.asarray(gti)
    times = np.asarray(times)
    startidx, stopidx = gti_border_bins(gti, times, dt=dt)

    for s, e, idx0, idx1 in zip(gti[:, 0], gti[:, 1], startidx, stopidx):
        yield s, e, idx0, idx1


def generate_indices_of_segment_boundaries_unbinned(times, gti, segment_size):
    """
    Get the indices of events from different segments of the observation.

    This is a generator, yielding the boundaries of each segment and the
    corresponding indices in the time array.

    Parameters
    ----------
    times : float `np.array`
        Array of times.
    gti : [[gti00, gti01], [gti10, gti11], ...]
        Good time intervals.
    segment_size : float
        Length of segments.

    Yields
    -------
    t0: float
        Start time of current segment.
    t1: float
        End time of current segment.
    startidx: int
        Start index of the current segment in the time array.
    stopidx: int
        End index of the current segment in the time array. Note that this is
        larger by one, so that `time[startidx:stopidx]` returns the correct
        time interval.

    Examples
    --------
    >>> times = [0.1, 0.2, 0.5, 0.8, 1.1]
    >>> gtis = [[0, 0.55], [0.6, 2.1]]
    >>> vals = generate_indices_of_segment_boundaries_unbinned(times, gtis, 0.5)
    >>> v0 = next(vals)
    >>> np.allclose(v0[:2], [0, 0.5])
    True
    >>> # Note: 0.5 is not included in the interval
    >>> np.allclose(v0[2:], [0, 2])
    True
    >>> v1 = next(vals)
    >>> np.allclose(v1[:2], [0.6, 1.1])
    True
    >>> # Again: 1.1 is not included in the interval
    >>> np.allclose(v1[2:], [3, 4])
    True
    """
    gti = np.asarray(gti)
    times = np.asarray(times)

    start, stop = time_intervals_from_gtis(gti, segment_size)

    startidx = np.asarray(np.searchsorted(times, start))
    stopidx = np.asarray(np.searchsorted(times, stop))

    for s, e, idx0, idx1 in zip(start, stop, startidx, stopidx):
        yield s, e, idx0, idx1


def generate_indices_of_segment_boundaries_binned(times, gti, segment_size,
                                                  dt=None):
    """
    Get the indices of binned times from different segments of the observation.

    This is a generator, yielding the boundaries of each segment and the
    corresponding indices in the time array

    Parameters
    ----------
    times : float `np.array`
        Array of times, uniformly sampled
    gti : [[gti00, gti01], [gti10, gti11], ...]
        good time intervals
    segment_size : float
        length of segments

    Yields
    -------
    t0: float
        First time value, from the time array, in the current segment
    t1: float
        Last time value, from the time array, in the current segment
    startidx: int
        Start index of the current segment in the time array
    stopidx: int
        End index of the current segment in the time array. Note that this is
        larger by one, so that `time[startidx:stopidx]` returns the correct
        time interval.

    Examples
    --------
    >>> times = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]
    >>> gtis = [[0.05, 0.55]]
    >>> vals = generate_indices_of_segment_boundaries_binned(times, gtis, 0.5, dt=0.1)
    >>> v0 = next(vals)
    >>> np.allclose(v0[:2], [0.05, 0.55])
    True
    >>> np.allclose(v0[2:], [0, 5])
    True
    """
    gti = np.asarray(gti)
    times = np.asarray(times)
    startidx, stopidx = bin_intervals_from_gtis(gti, segment_size, times,
                                                dt=dt)

    if dt is None:
        dt = 0
    for idx0, idx1 in zip(startidx, stopidx):
        yield times[idx0] - dt / 2, times[min(idx1, times.size - 1)] - dt / 2,\
              idx0, idx1
