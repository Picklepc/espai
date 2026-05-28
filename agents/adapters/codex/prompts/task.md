## Task: {{ task.title }}

**Project:** {{ project.name }}
**Template:** {{ task.template }}
**Created:** {{ task.created }}

### Description

{{ task.description }}

### Allowed paths

You may only read and write files under these paths:
{% for path in allowed_paths %}
- `{{ path }}`
{% endfor %}

### Acceptance criteria

{% for criterion in task.acceptance_criteria %}
- {{ criterion }}
{% endfor %}

### Additional context

{{ task.context | default("None provided.") }}

---

Begin implementation. Explain your plan briefly, then make the changes.
After changes, list every file you modified and summarize what changed and why.
