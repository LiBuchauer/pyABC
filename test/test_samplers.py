import multiprocessing
import pytest
import scipy as sp
import scipy.stats as st
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from pyabc import (ABCSMC, RV, Distribution,
                   MedianEpsilon,
                   PercentileDistanceFunction, SimpleModel,
                   ConstantPopulationSize)
from pyabc.sampler import (SingleCoreSampler, MappingSampler,
                           MulticoreParticleParallelSampler,
                           DaskDistributedSampler,
                           ConcurrentFutureSampler,
                           MulticoreEvalParallelSampler,
                           RedisEvalParallelSamplerServerStarter)


def multi_proc_map(f, x):
    with multiprocessing.Pool() as pool:
        res = pool.map(f, x)
    return res


class GenericFutureWithProcessPool(ConcurrentFutureSampler):
    def __init__(self, map=None):
        cfuture_executor = ProcessPoolExecutor(max_workers=8)
        client_max_jobs = 8
        super().__init__(cfuture_executor, client_max_jobs)


class GenericFutureWithProcessPoolBatch(ConcurrentFutureSampler):
    def __init__(self, map=None):
        cfuture_executor = ProcessPoolExecutor(max_workers=8)
        client_max_jobs = 8
        batchsize = 15
        super().__init__(cfuture_executor, client_max_jobs,
                         batchsize=batchsize)


class GenericFutureWithThreadPool(ConcurrentFutureSampler):
    def __init__(self, map=None):
        cfuture_executor = ThreadPoolExecutor(max_workers=8)
        client_max_jobs = 8
        super().__init__(cfuture_executor, client_max_jobs)


class MultiProcessingMappingSampler(MappingSampler):
    def __init__(self, map=None):
        super().__init__(multi_proc_map)


class DaskDistributedSamplerBatch(DaskDistributedSampler):
    def __init__(self, map=None):
        batchsize = 20
        super().__init__(batchsize=batchsize)


@pytest.fixture(params=[RedisEvalParallelSamplerServerStarter,
                        MulticoreEvalParallelSampler,
                        SingleCoreSampler,
                        MultiProcessingMappingSampler,
                        MulticoreParticleParallelSampler,
                        MappingSampler, DaskDistributedSampler,
                        GenericFutureWithThreadPool,
                        GenericFutureWithProcessPool,
                        GenericFutureWithProcessPoolBatch,
                        DaskDistributedSamplerBatch
                        ])
def sampler(request):
    s = request.param()
    yield s
    try:
        s.cleanup()
    except AttributeError:
        pass


@pytest.fixture(params=[1, 2])
def n_sim(request):
    return request.param


def test_two_competing_gaussians_multiple_population(
        db_path, sampler, n_sim):
    # Define a gaussian model
    sigma = .5

    def model(args):
        return {"y": st.norm(args['x'], sigma).rvs()}

    # We define two models, but they are identical so far
    models = [model, model]
    models = list(map(SimpleModel, models))

    # However, our models' priors are not the same. Their mean differs.
    mu_x_1, mu_x_2 = 0, 1
    parameter_given_model_prior_distribution = [
        Distribution(x=RV("norm", mu_x_1, sigma)),
        Distribution(x=RV("norm", mu_x_2, sigma))
    ]

    # We plug all the ABC setup together
    nr_populations = 3
    pop_size = ConstantPopulationSize(40, nr_samples_per_parameter=n_sim)
    abc = ABCSMC(models, parameter_given_model_prior_distribution,
                 PercentileDistanceFunction(measures_to_use=["y"]),
                 pop_size,
                 eps=MedianEpsilon(.2),
                 sampler=sampler)

    # Finally we add meta data such as model names and
    # define where to store the results
    # y_observed is the important piece here: our actual observation.
    y_observed = 1
    abc.new(db_path, {"y": y_observed})

    # We run the ABC with 3 populations max
    minimum_epsilon = .05
    history = abc.run(minimum_epsilon, max_nr_populations=nr_populations)

    # Evaluate the model probabililties
    mp = history.get_model_probabilities(history.max_t)

    def p_y_given_model(mu_x_model):
        res = st.norm(mu_x_model, sp.sqrt(sigma**2 + sigma**2)).pdf(y_observed)
        return res

    p1_expected_unnormalized = p_y_given_model(mu_x_1)
    p2_expected_unnormalized = p_y_given_model(mu_x_2)
    p1_expected = p1_expected_unnormalized / (p1_expected_unnormalized
                                              + p2_expected_unnormalized)
    p2_expected = p2_expected_unnormalized / (p1_expected_unnormalized
                                              + p2_expected_unnormalized)
    assert history.max_t == nr_populations-1
    # the next line only tests if we obtain correct numerical types
    assert abs(mp.p[0] - p1_expected) + abs(mp.p[1] - p2_expected) < sp.inf


def test_in_memory():
    sampler = RedisEvalParallelSamplerServerStarter()
    db_path = "sqlite://"
    n_sim = 1
    test_two_competing_gaussians_multiple_population(db_path, sampler, n_sim)
