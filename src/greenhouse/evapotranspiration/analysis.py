from dataclasses import dataclass
from math import fsum, sqrt
from statistics import median
from .contracts import DailyTarget


@dataclass(frozen=True)
class WaterModel:
    features: tuple
    bias: float
    coefficients: tuple
    trained: int
    clip_l: float


def spread(column):
    mean = fsum(column)/len(column)
    standard = sqrt(fsum((x-mean)**2 for x in column)/len(column))
    return mean, max(standard, 0.001)


def solve(matrix, values):
    expected = len(values)
    grid = [list(row) + [target] for row,target in zip(matrix, values, strict=True)]
    for col in range(expected):
        pivot = max(range(col, expected), key=lambda row: abs(grid[row][col]))
        grid[pivot],grid[col] = grid[col],grid[pivot]
        scale = grid[col][col]
        if abs(scale) < 1e-10:
            raise ValueError("ILL_CONDITIONED")
        grid[col] = [value / scale for value in grid[col]]
        for row in range(expected):
            if row != col:
                ratio = grid[row][col]
                grid[row] = [a-ratio*b for a,b in zip(grid[row],grid[col], strict=True)]
    return tuple(row[-1] for row in grid)


def train(examples, *, ridge=1.0):
    if len(examples) < 4 or ridge <= 0:
        raise ValueError("CALIBRATION_NEEDS_HISTORY")
    vectors, targets = zip(*examples, strict=True)
    stats = tuple(spread(list(col)) for col in zip(*vectors,strict=True))
    mapped = [tuple((x-mean)/scale for x,(mean,scale) in zip(v,stats,strict=True)) for v in vectors]
    size = len(stats)
    bias = fsum(targets) / len(targets)
    gram = [[fsum(row[i]*row[j] for row in mapped)+(ridge if i==j else 0.0) for j in range(size)] for i in range(size)]
    covariance = [fsum((y-bias)*row[i] for row,y in zip(mapped,targets,strict=True)) for i in range(size)]
    coefficients = solve(gram,covariance)
    return WaterModel(stats,bias,coefficients,len(targets),max(targets)*1.4)


def forecast(fitted, features):
    linear = fsum(coef*(x-mean)/scale for coef,x,(mean,scale) in zip(fitted.coefficients,features,fitted.features,strict=True))
    return min(fitted.clip_l,max(0.0,fitted.bias + linear))


def predict(fitted, requests):
    return [forecast(fitted, item) for item in requests]


def rule_reference(samples):
    if not samples:
        return None
    return median(y for _,y in samples)
