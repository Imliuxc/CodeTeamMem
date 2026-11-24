"""Typed Stage 1 outcomes; no provider imports or network side effects."""


class EnvError(RuntimeError):
    category = 'env_error'


class CalibrationFailed(ValueError):
    def __init__(self, message, category='model_wrong'):
        super().__init__(message)
        if category not in {'model_wrong', 'parse_error'}:
            raise ValueError('invalid business failure category')
        self.category = category

