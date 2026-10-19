import { useId, useState } from "react";
import type { CatalogDataset } from "@/api";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Field, FieldLabel } from "@/components/ui/field";
export function TaskCatalog({
  dataset,
  selected,
  onSelect,
}: {
  dataset: CatalogDataset;
  selected?: string[];
  onSelect?: (names: string[]) => void;
}) {
  const [open, setOpen] = useState(false),
    [query, setQuery] = useState(""),
    [limit, setLimit] = useState(20);
  const id = useId(),
    tasks = dataset.tasks || [],
    budgets = dataset.author_parameters.discovery?.budgets || [];
  const budgetByTask = new Map(budgets.map((b) => [b.task, b]));
  const filtered = tasks.filter((t) =>
    `${t.name} ${t.package || ""}`.toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <div className="flex flex-col gap-3">
      <Button
        variant="outline"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        {open ? "收起" : "展开"}任务与作者预算（{tasks.length} 个任务 /{" "}
        {budgets.length} 条预算）{selected ? ` · 已选 ${selected.length}` : ""}
      </Button>
      {open && (
        <>
          <Field>
            <FieldLabel htmlFor={id}>筛选任务名称或包名</FieldLabel>
            <Input
              id={id}
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setLimit(20);
              }}
            />
          </Field>
          <p>
            匹配 {filtered.length} 个；未知预算显示“未知”，0
            秒为有效值。预算仅单任务，总时长另含准备与重复尝试。
          </p>
          <div className="task-budget-list">
            {filtered.slice(0, limit).map((task) => {
              const budget =
                budgetByTask.get(task.package || "") ||
                budgetByTask.get(task.name);
              return (
                <div key={task.name} className="task-budget-row">
                  <div>
                    {onSelect && selected && (
                      <input
                        type="checkbox"
                        aria-label={`选择任务 ${task.name}`}
                        checked={selected.includes(task.name)}
                        onChange={(e) =>
                          onSelect(
                            e.target.checked
                              ? [...selected, task.name]
                              : selected.filter((n) => n !== task.name),
                          )
                        }
                      />
                    )}
                    <span className="break-all select-text">{task.name}</span>
                    {task.package && task.package !== task.name && (
                      <details>
                        <summary>完整包名</summary>
                        <p className="break-all select-text">{task.package}</p>
                      </details>
                    )}
                  </div>
                  <div>
                    agent：
                    {budget?.agent_seconds == null
                      ? "未知"
                      : `${budget.agent_seconds} 秒`}
                  </div>
                  <div>
                    verifier：
                    {budget?.verifier_seconds == null
                      ? "未知"
                      : `${budget.verifier_seconds} 秒`}
                  </div>
                </div>
              );
            })}
          </div>
          {filtered.length > limit && (
            <Button variant="outline" onClick={() => setLimit(limit + 20)}>
              再显示 20 个
            </Button>
          )}
        </>
      )}
    </div>
  );
}
