# Architecture decision: deterministic core before agent orchestration

## Decision

The project begins with a deterministic, read-only BPMN core and exposes it
through MCP. LangGraph and the LLM are introduced only after the tool contracts
and regression tests are stable.

## Why

An LLM must not infer graph facts that can be calculated exactly. The following
remain deterministic:

- XML loading;
- ID and reference handling;
- lane membership;
- predecessor and successor lookup;
- reachability;
- path lookup;
- structural validation;
- future atomic XML patch application.

The model will later handle:

- interpreting ambiguous business requests;
- choosing which inspection tools to call;
- producing a grounded modification plan;
- deciding how to react to validation feedback;
- explaining trade-offs;
- escalating uncertainty to a human.

## Safety boundary

The first MCP server is read-only. Future write tools will:

1. operate on a copy;
2. accept typed patch objects;
3. support only allow-listed transformations;
4. return a diff;
5. run validation automatically;
6. require approval before promotion;
7. preserve rollback information.
