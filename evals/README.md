# Agent evaluation set

`gold.json` covers requirement extraction, insufficient-evidence abstention, material versus editorial source changes, grounded planner answers, refusal, and temporary what-if behavior. Run the credential-free regression subset from the repository root:

```powershell
python evals/run.py
```

The report separates executed deterministic cases from AI cases that are ready for a credentialed run. Pass/fail checks measure required facts, citation presence, correct abstention, material change behavior, and the invariant that a what-if result is not persisted. Add discovered failures to the gold set instead of editing expected answers after a run.

For Chalk Agent Evals, upload `gold.json` as the dataset, use the case `kind` as a slice, deploy the existing task/provider code, and reproduce the same pass/fail fields as scorers. Record the Git commit in evaluation metadata. This follows Chalk's dataset → task → scorer → run workflow and keeps local regression results comparable with the hosted run.
