Ниже данные для оценки звонка. Верни ответ строго в формате JSON-объекта.

Ограничения:
1. Никакого markdown и тройных кавычек.
2. Никакого текста до или после JSON.
3. raw_coef только из множества [0, 0.5, 1].
4. module_weight_percent брать из modules_catalog.
5. weighted_points = raw_coef * module_weight_percent.
6. overall_score_0_100 = round(sum(weighted_points), 2).
7. В modules должен быть каждый модуль из modules_catalog ровно один раз.
8. Если raw_coef = 1 → в объекте модуля только: block_name, module_name, raw_coef, weighted_points.
9. Если raw_coef < 1 → добавь comment (до 120 символов) и task (до 100 символов, обязательна).
10. final_summary — не длиннее 120 символов, только словесный итог, без чисел и слова "балл".

Контекст:
- export_id: __EXPORT_ID__
- standard_version_id: __STANDARD_VERSION_ID__
- schema_version: qa_call_analysis_v1

Минимальный JSON-ответ:
{
  "schema_version": "qa_call_analysis_v1",
  "export_id": __EXPORT_ID__,
  "standard_version_id": __STANDARD_VERSION_ID__,
  "overall_score_0_100": 74.5,
  "final_summary": "Краткий словесный итог звонка.",
  "modules": [
    {
      "block_name": "Установление контакта",
      "module_name": "Приветствие, согласно принятому стандарту*",
      "raw_coef": 0.5,
      "weighted_points": 1.5,
      "comment": "Отдел не назван в приветствии.",
      "task": "Называй отдел в первые 5 секунд разговора."
    },
    {
      "block_name": "Установление контакта",
      "module_name": "Обратиться к клиенту по имени не менее 2х раз",
      "raw_coef": 1,
      "weighted_points": 3.0
    }
  ],
  "calculation_check": {
    "sum_weighted_points": 74.5,
    "rounded_overall_score_0_100": 74.5,
    "formula": "overall_score_0_100 = round(sum(weighted_points), 2)"
  }
}
