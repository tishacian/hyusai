/** The zero-shot family's public contract; no external weights are needed by mocked UI QA. */
export function addFoundationCatalog(catalog: any): void {
  const fields = catalog.families.find((family: any) => family.key === 'forecasting').spec_fields;
  const accepted = ['time_column', 'shape', 'series_columns', 'horizon', 'frequency', 'interval_level', 'backtest_folds', 'fill'];
  catalog.families.push({key:'forecasting_deep',tasks:['forecasting'],runtime:'ml-deep',serving:'remote',available:true,
    spec_fields:fields.filter((field: any) => accepted.includes(field.key)).map((field: any) => ({...field,
      ...(field.key === 'horizon' ? {max:64} : {}),
      ...(field.key === 'backtest_folds' ? {max:5} : {}),
      ...(field.key === 'shape' ? {choices:['single','panel']} : {}),
      ...(field.key === 'fill' ? {choices:['refuse','zero']} : {}),
    }))});
  catalog.algos.push({key:'chronos_zero_shot',family:'forecasting_deep',available:true,tasks:['forecasting'],
    estimators:{forecasting:'skforecast.foundation.ForecasterFoundation'},scale:false,tags:['foundation','zero_shot'],knobs:[]});
}
