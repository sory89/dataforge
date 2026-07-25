select
    order_date,
    count(*) as nb_orders,
    sum(amount_eur) as revenue_eur
from {{ ref('stg_orders') }}
where status = 'completed'
group by order_date
order by order_date
