# Association radio — matrice de validation matérielle

Cette matrice consigne uniquement des essais effectués sur matériel réel. Elle
ne remplace pas le catalogue officiel intégré au composant : celui-ci couvre
chaque modèle proposé par l'interface, tandis que ces lignes servent de garde
fou de régression pour les parcours qui ont déjà été validés.

| Produit / environnement | Scénario validé | Résultat |
| --- | --- | --- |
| TYXIA 2600 / Tywell Pro | Association et dissociation de chaque voie A/B ; nettoyage de la configuration TYDOM | Validé |
| TYXIA 1410 | Association d'une voie à une télécommande existante, rattachement automatique, puis dissociation d'une voie sans supprimer les autres | Validé |
| TL 2000 | Association/dissociation par voie de télécommande | Validé |
| TYXIA 4620 | Dissociation complète puis réassociation en portail coulissant et portillon | Validé |
| TYWATT 5100 / essai Quiet | Association radio et reprise par rechargement ; la configuration native de la passerelle n'est jamais réécrite | Validé |
| Tysense Sun / Tywell Pro | Dissociation réussie ; réassociation corrigée pour écrire `sensorSun` au lieu du capteur générique | À revalider après déploiement de la correction |

## Invariants couverts par le code

- Chaque choix installable du catalogue officiel possède désormais une recette
  explicite `(catégorie, modèle)` pour l'écriture dans `/configs/file`.
- Un modèle inconnu ne reçoit jamais une recette par simple similarité de nom
  de catégorie.
- Les télécommandes et interrupteurs à voies (TYXIA 1410, TL 2000, TYXIA 2600
  et similaires) gardent leur traitement d'association par voie.
- Les produits qui publient leur propre configuration finale, notamment les
  compteurs comme le TYWATT 5100, ne sont pas écrasés pendant la découverte.
