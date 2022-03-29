##################################################
Stingray and Spectral Timing: A Brief Introduction
##################################################

Stingray is a Python library designed to perform times series analysis and related tasks on astronomical light curves.
It supports a range of commonly-used Fourier analysis techniques, as well as extensions for analyzing pulsar data, simulating data sets, and statistical modelling.
Stingray is designed to be easy to extend, and easy to incorporate into data analysis workflows and pipelines.

For a brief overview of the history and state-of-the-art in spectral timing, and for more information about the design and capabilities of Stingray, please refer to `Huppenkothen et al. (2019) <https://ui.adsabs.harvard.edu/abs/2019ApJ...881...39H/abstract>`_.

Features
========
Current Capabilities
--------------------

Currently implemented functionality in this library comprises:

* loading event lists from fits files of a few missions (RXTE/PCA, NuSTAR/FPM, XMM-Newton/EPIC, NICER/XTI)
* constructing light curves from event data, various operations on light curves (e.g. addition, subtraction, joining, and truncation)
* Good Time Interval operations
* power spectra in Leahy, rms normalization, absolute rms and no normalization
* averaged power spectra
* dynamical power spectra
* maximum likelihood fitting of periodograms/parametric models
* (averaged) cross spectra
* coherence, time lags
* cross correlation functions
* RMS spectra and lags (time vs energy, time vs frequency); *needs testing*
* covariance spectra; *needs testing*
* bispectra; *needs testing*
* (Bayesian) quasi-periodic oscillation searches
* simulating a light curve with a given power spectrum
* simulating a light curve from another light curve and a 1-d (time) or 2-d (time-energy) impulse response
* simulating an event list from a given light curve _and_ with a given energy spectrum
* pulsar searches with Epoch Folding, :math:`Z^2_n` test

Future Plans
------------

We welcome feature requests: if you need a particular tool that's currently not available or have a new method you think might be usefully implemented in Stingray, please :doc:`get in touch <contributing>`!

Other future additions we are currently implementing are:

* bicoherence
* phase-resolved spectroscopy of quasi-periodic oscillations
* Fourier-frequency-resolved spectroscopy
* power colours
* full HEASARC-compatible mission support
* pulsar searches with :math:`H`-test
* binary pulsar searches

Platform-specific issues
------------------------

Windows uses an internal 32-bit representation for ``int``. This might create numerical errors when using large integer numbers (e.g. when calculating the sum of a light curve, if the ``lc.counts`` array is an integer).
On Windows, we automatically convert the ``counts`` array to float. The small numerical errors should be a relatively small issue compare to the above.

Presentations
=============

Members of the Stingray team have given a number of presentations which introduce Stingray.
These include:
- `2nd Severo Ochoa School on Statistics, Data Mining, and Machine Learning (2021) <https://github.com/abigailStev/timeseries-tutorial>`_
- `9th Microquasar Workshop (2021) <https://speakerdeck.com/abigailstev/time-series-exploration-with-stingray>`_
- `European Week of Astronomy and Space Science (2018) <http://ascl.net/wordpress/2018/05/24/software-in-astronomy-symposium-presentations-part-3/>`_
- `ADASS (Astronomical Data Analysis Software and Systems; meeting 2017, proceedings 2020) <https://ui.adsabs.harvard.edu/abs/2020ASPC..522..521M/abstract>`_
- `AAS 16th High-Energy Astrophysics Division meeting (2017) <https://speakerdeck.com/abigailstev/stingray-open-source-spectral-timing-software>`_
- `European Week of Astronomy and Space Science 2017 <http://ascl.net/wordpress/2017/07/23/special-session-on-and-about-software-at-ewass-2017/>`_
- `Python in Astronomy (2016) <https://speakerdeck.com/abigailstev/stingray-pyastro16>`_
