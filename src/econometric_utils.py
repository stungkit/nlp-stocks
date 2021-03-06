from collections.abc import Iterable
import warnings

import numpy as np
from statsmodels.tsa.stattools import grangercausalitytests
from scipy import stats
import statsmodels.tsa.api as smt
import statsmodels.tsa.statespace.tools as statstools
from statsmodels.tsa.api import VAR, DynamicVAR


# Reject any null hypothesis if p value is below a significant level / statistic value is more extreme than the related critical value
# Weak assumption: If we can't reject a null hypothesis we assume that it's true
# p=100% would mean the null hypothesis is correct. Below 5% we can "safely" reject it
# Link 1: https://stats.stackexchange.com/questions/55805/how-do-you-interpret-results-from-unit-root-tests)
# My Post: https://stats.stackexchange.com/questions/317133/how-to-interpret-kpss-test/371119#371119

# Null hypothesis: is level stationary (with noise) = I(0)
# For instance a ‘shock’ dies away with stationarity but is persistent if non stationary.
def is_stationary(X, debug=True):  # = not able to reject null hypothesis
    # Null hypothesis: x is stationary (not trend stationary); Note: test tends to reject too often
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore")
        kpss_stat, p_value, lags, critical_values = smt.kpss(X)
    if debug:
        print('-'*10, ' KPSS ', '-'*10,)
        print(f'{kpss_stat}, {p_value}, {lags}, {critical_values}')
    return abs(kpss_stat) < abs(critical_values['5%'])
    # Same as return p_value > 0.05


# Null hypothesis: has unit root = I(1)
def has_unit_root(X, debug=True):  # = not able to reject null hypothesis
    # Null hypothesis: x has a unit root (= is not stationary, might be trend stationary)
    adf_stat, p_value, used_lag, nobs, critical_values, icbest = smt.adfuller(X)
    if debug:
        print('-'*10, ' ADF ', '-'*10,)
        print(f'{adf_stat}, {p_value}, {used_lag}, {critical_values}')
    return abs(adf_stat) < abs(critical_values['5%'])
    # Same as return p_value > 0.05


def get_order_of_integration(X, debug=True):
    if has_unit_root(X, debug=debug):
        return 1
    if is_stationary(X, debug=debug):
        return 0
    return 2  # just assumption. usually this shouldn't happen


# Uses the augmented Engle-Granger two-step cointegration test
def get_best_cointegration_certainty(X1, X2, debug=False):  # = able to reject null hypothesis
    X1_order = get_order_of_integration(X1, debug=False)
    X2_order = get_order_of_integration(X2, debug=False)
    if debug:
        print('-'*10, ' COINT ', '-'*10,)
        print(f'X1: I({X1_order}) - X2: I({X2_order})')
#     assert X1_order, f'Timeseries X1 need to be of I(1) but was {X1_order}'
#     assert X2_order, f'Timeseries X2 need to be of I(1) but was {X2_order}'
    min_p_value = 1
    # Null hypothesis: X1 & X2 are not cointegrated (= is not stationary, might be trend stationary)
    for trend_type in ['c', 'ct', 'ctt']:
        coint_stat, p_value, critical_values = smt.coint(X1, X2, trend_type, maxlag=10)
        if debug:
            print(f'{trend_type}: {coint_stat:.2f}, {p_value:.2f}, {critical_values}')
        min_p_value = min(min_p_value, p_value)
    return min_p_value


# Uses the augmented Engle-Granger two-step cointegration test
def are_cointegrated(X1, X2, debug=True):  # = able to reject null hypothesis
    min_p_value = get_best_cointegration_certainty(X1, X2, debug)
#   return abs(coint_stat) > abs(critical_values[1])
    return min_p_value < 0.05


def moving_average(x, N, fill=True):
    return np.concatenate([x for x in [
        [None]*(N // 2 + N % 2)*fill,
        np.convolve(x, np.ones((N,))/N, mode='valid'),
        [None]*(N // 2)*fill,
    ] if len(x)]).astype(float)


def get_granger_causality(x, y, lag=1):
    matrix = np.array([y, x]).T
    if isinstance(lag, int):
        lag = [lag]
    assert isinstance(lag, Iterable)
    lags = list(lag)
    test_result = grangercausalitytests(matrix, maxlag=max(lags), verbose=False)
    return [test_result[x][0]['ssr_ftest'][1] for x in lags]


# --------- Feature generation ----------------------------------------------- #


def add_movements(price, verbose=False):
    price['ctc'] = (price.close / price.close.shift(1))
    price['oto'] = (price.open / price.open.shift(1))  # price.open.pct_change() + 1
    price['otc'] = (price.close / price.open)
    price['cto'] = (price.open / price.close.shift(1))
    price['lret'] = np.log(price['otc']) * 100
    price['boxcox'], argmll_lmbda = stats.boxcox(price['otc'])
    if verbose:
        print(f'Lambda for Box-Cox maximizing the Max. Likelihood: {argmll_lmbda:.2f}')
    return price[1:]


def get_daily_rel_change(v):
    return np.concatenate([[0], (v[1:].values / v[:-1].values) - 1])


def get_daily_price(start, rel_v):
    return start * (rel_v + 1).cumprod()


def normalize(p, gspc_r):
    r = get_daily_rel_change(p)
    return get_daily_price(p.iloc[0], r - gspc_r)


if __name__ == '__main__':
    print(are_cointegrated(
        np.arange(5, 105) + np.random.rand(100),
        np.arange(100) * np.arange(100) * np.arange(100) * np.array(list(reversed(np.arange(100)))),
        debug=True))

    a = np.random.random(50)
    b = np.arange(5, 55)
    # b = np.random.random(10)
    matrix = np.array([b, a]).T
    print(grangercausalitytests(matrix, maxlag=2, verbose=True))
    # _ = plt.plot(matrix)
