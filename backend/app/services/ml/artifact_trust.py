"""Reader-owned qualified type names. Never expand trust from bundle metadata."""

TABULAR_TYPES = frozenset(
    {
        "functools.partial",
        "numpy.dtype",
        "scipy.interpolate._bsplines.BSpline",
        "scipy.interpolate._bsplines._BSpline",
        "sklearn.calibration._CalibratedClassifier",
        "sklearn.calibration._SigmoidCalibration",
        "sklearn.utils.validation.check_array",
        "sklearn.ensemble._hist_gradient_boosting.predictor.TreePredictor",
        # The fitted tree of every sklearn forest and boosting stage. The catalog
        # trains ``random_forest`` and the harness records this type; without it
        # such a model trained but could not be served (M5 found it via TreeSHAP).
        "sklearn.tree._tree.Tree",
        "skrub._apply_to_each_col.ApplyToEachCol",
        "skrub._check_input.CheckInputDataFrame",
        "skrub._clean_categories.CleanCategories",
        "skrub._clean_null_strings.CleanNullStrings",
        "skrub._dataframe._common.is_any_date",
        "skrub._dataframe._common.is_categorical",
        "skrub._dataframe._common.is_numeric",
        "skrub._datetime_encoder.DatetimeEncoder",
        "skrub._datetime_encoder._SplineEncoder",
        "skrub._drop_uninformative.DropUninformative",
        "skrub._duration_to_float.DurationToFloat",
        "skrub._minhash_encoder.MinHashEncoder",
        "skrub._squashing_scaler.SquashingScaler",
        "skrub._squashing_scaler._MinMaxScaler",
        "skrub._string_encoder.StringEncoder",
        "skrub._table_vectorizer.PassThrough",
        "skrub._table_vectorizer.ShortReprDict",
        "skrub._table_vectorizer.TableVectorizer",
        "skrub._table_vectorizer._created_by_predicate",
        "skrub._to_categorical.ToCategorical",
        "skrub._to_datetime.ToDatetime",
        "skrub._to_float.ToFloat",
        "skrub._to_str.ToStr",
        "skrub._utils.LRUDict",
        "skrub.selectors._base.All",
        "skrub.selectors._base.And",
        "skrub.selectors._base.Cols",
        "skrub.selectors._base.Filter",
        "skrub.selectors._base.Sub",
        "skrub.selectors._selectors._cardinality_below",
    }
)
FORECAST_TYPES = frozenset(
    {
        "builtins.dict",
        "sklearn.ensemble._hist_gradient_boosting.predictor.TreePredictor",
        "numpy.dtype",
        "pandas._libs.tslibs.offsets.Hour",
        "pandas._libs.tslibs.offsets.Day",
        "pandas._libs.tslibs.offsets.Week",
        "pandas._libs.tslibs.offsets.MonthBegin",
        "pandas._libs.tslibs.offsets.QuarterBegin",
        "pandas.core.frame.DataFrame",
        "pandas.core.indexes.datetimes.DatetimeIndex",
        "skforecast.direct._forecaster_direct.ForecasterDirect",
        "skforecast.preprocessing._calendar.CalendarFeatures",
        "skforecast.preprocessing._preprocessing.QuantileBinner",
        "skforecast.recursive._forecaster_recursive.ForecasterRecursive",
        "skforecast.recursive._forecaster_recursive_multiseries.ForecasterRecursiveMultiSeries",
    }
)
# M4.3 imported sklearn pipelines. Beyond skops' own defaults (sklearn
# estimators, numpy ufuncs, plain containers) only two fitted *data*
# structures, rebuilt from arrays and never calling user code: dtype
# descriptors, and the node storage of decision trees, forests and gradient
# boosting. The latter is indexed without bounds checks by scikit-learn, so an
# imported model's trees are structurally checked in the isolated reader
# before its first prediction. HistGradientBoosting's TreePredictor is left
# out until its node arrays get the same check. No functools.partial, no
# builtins callable, no numpy function object, no module of the importer's.
EXTERNAL_TYPES = frozenset(
    {
        "numpy.dtype",
        "sklearn.tree._tree.Tree",
    }
)
TRUSTED_PROFILES = {
    "tabular-skops-v1": TABULAR_TYPES,
    "clustering-skops-v1": frozenset({"numpy.dtype"}),
    "forecast-skops-v1": FORECAST_TYPES,
    "external-sklearn-skops-v1": EXTERNAL_TYPES,
}
