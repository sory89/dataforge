# ADR-005 : Monitoring — mesurer la qualite LLM en production

## Contexte

Le gate d'evaluation (ADR-003) mesure la qualite avant le merge, sur 12 questions
dont la reponse exacte est connue. En production, les questions sont inconnues :
impossible de savoir si le SQL genere est *juste*.

Surveiller uniquement le CPU et la memoire ne dirait rien du probleme reel. Un
service Text-to-SQL peut consommer 5 % de CPU, repondre en 200 ms et produire du
SQL faux a chaque requete.

## Decision

### Trois signaux indirects de qualite

En l'absence de verite terrain, ces trois taux revelent une regression :

| Signal | Ce qu'il indique |
|---|---|
| `invalid_sql` | Erreur du binder DuckDB : colonne inventee, `GROUP BY` errone. C'est l'equivalent production de l'unique cas en echec du golden set. |
| `empty` | Requete valide retournant zero ligne — souvent un contresens semantique. Le prompt v5 avait produit un `WHERE order_date > CURRENT_DATE` parfaitement valide et absurde. |
| `unsafe_sql` | Rejets du garde-fou lecture seule. En hausse : soit derive du modele, soit sondage du service. |

Toutes ces metriques portent le label `prompt_version`, ce qui permet de comparer
deux prompts **en production** et pas seulement sur le golden set — precisement ce
qui manquait pour valider v5 honnetement.

### Ressources : trois niveaux

- **Process** : `process_cpu_seconds_total`, `process_resident_memory_bytes`,
  exposes automatiquement par `prometheus_client`.
- **Conteneur** : `container_cpu_usage_seconds_total`,
  `container_memory_working_set_bytes` et `container_cpu_cfs_throttled_seconds_total`
  via cAdvisor embarque dans le kubelet. Le throttling est le signal utile : un
  conteneur bride par sa limite CPU repond lentement sans que l'usage paraisse
  anormal.
- **Cluster** : `kube-state-metrics`, avec les CRD `rollouts` et `analysisruns`
  ajoutees au ClusterRole pour suivre l'etat des deploiements Argo.

### Rollback automatique sur degradation de qualite

Le Rollout gagne une `postPromotionAnalysis` interrogeant Prometheus :

```
(sum(rate(dataforge_queries_total{outcome=~"invalid_sql|llm_error"}[5m])) or vector(0))
/ clamp_min(sum(rate(dataforge_queries_total[5m])) or vector(0), 0.0001)
```

Cinq mesures espacees de 60 s, seuil a 25 %, `failureLimit: 2`. Un depassement
declenche un **rollback automatique** vers la revision precedente.

Deux details qui font la difference entre une regle qui marche et une qui nuit :

1. **`clamp_min` evite la division par zero.** Sans trafic, le denominateur vaut 0
   et la requete retourne `NaN`, ce qu'Argo interprete comme un echec. Une analyse
   qui echoue faute de trafic annulerait des deploiements sains.
2. **`postPromotion` et non `prePromotion`.** Avant bascule, la nouvelle revision
   ne recoit aucun trafic : il n'y a rien a mesurer. Le smoke test existant reste
   en pre-promotion (verification binaire de disponibilite), l'analyse de qualite
   vient apres.

### Series preinitialisees a zero

`metrics.preinitialize()` cree les series de chaque `outcome` au demarrage. Sans
cela, `rate(...{outcome="invalid_sql"})` ne retourne rien avant le premier echec,
et un tableau de bord vide se confond avec un tableau de bord sain.

## Consequences

- Le tableau de bord Grafana est **versionne dans Git** (ConfigMap JSON provisionne),
  pas construit a la main dans l'interface : il se recree a l'identique sur un
  cluster neuf.
- Prometheus utilise un `emptyDir` avec 12 h de retention : suffisant pour la
  demonstration, insuffisant pour de la production, ou un PVC et un stockage long
  terme seraient necessaires.
- Grafana est en acces anonyme lecture avec un mot de passe admin en clair dans le
  manifeste. Acceptable sur un cluster local isole, a remplacer par un Secret et
  une authentification reelle des que le cluster est expose.
- Le `metric_relabel_configs` du job cAdvisor ne conserve que cinq familles de
  metriques : sans ce filtre, cAdvisor produit un volume disproportionne pour un
  cluster de demonstration.
