export interface TaskTrailItem {
  key: string
  label: string
}

export function taskTrail<T extends { sequence: number }>(
  steps: T[],
  describe: (step: T) => string,
  outcome?: string,
): TaskTrailItem[] {
  const items: TaskTrailItem[] = []
  for (const step of steps) {
    const label = describe(step)
    if (items.at(-1)?.label !== label) items.push({ key: String(step.sequence), label })
  }
  if (outcome && items.at(-1)?.label !== outcome) items.push({ key: 'outcome', label: outcome })
  return items
}
