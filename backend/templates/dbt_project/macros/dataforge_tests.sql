{% test dataforge_unique_combination(model, columns) %}
select {{ columns | join(', ') }}, count(*) as _n
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1
{% endtest %}

{% test dataforge_expression_is_true(model, expression) %}
select *
from {{ model }}
where not ({{ expression }})
{% endtest %}
