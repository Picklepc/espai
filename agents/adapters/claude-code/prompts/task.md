## Task: {{ task.title }}

**Project:** {{ project.name }}
**Template:** {{ task.template }}

### Description

{{ task.description }}

### Allowed paths (read + write)

{% for path in allowed_paths %}
- `{{ path }}`
{% endfor %}

### Acceptance criteria

{% for criterion in task.acceptance_criteria %}
- [ ] {{ criterion }}
{% endfor %}

{% if task.context %}
### Context

{{ task.context }}
{% endif %}

---

Work through this task. Keep changes minimal and targeted.
When done, output a summary in this format:

**Files changed:**
- `path/to/file` — reason

**Notes for reviewer:**
(anything that needs human attention before merge)
