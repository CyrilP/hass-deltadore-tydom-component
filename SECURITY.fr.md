# Politique de sécurité

[English](SECURITY.md) | **Français**

## Versions prises en charge

Les correctifs de sécurité sont appliqués à la dernière version publiée ainsi
qu'à la branche `main`. Les versions antérieures ne sont pas maintenues. Les
utilisateurs doivent effectuer une mise à niveau avant de signaler un problème
qui pourrait déjà avoir été corrigé.

## Signaler une vulnérabilité

N'ouvrez pas de ticket public ni de pull request pour signaler une
vulnérabilité de sécurité présumée. Utilisez le
[formulaire privé de signalement des vulnérabilités](https://github.com/CyrilP/hass-deltadore-tydom-component/security/advisories/new)
de GitHub afin que les mainteneurs puissent mener leur enquête avant toute
divulgation publique.

Dans la mesure du possible, indiquez :

- les versions concernées de l'intégration et de Home Assistant ;
- une description de l'impact et des conditions nécessaires pour reproduire
  le problème ;
- les étapes minimales de reproduction ou une démonstration du problème ;
- les journaux pertinents après suppression des identifiants et informations
  personnelles ;
- toute mesure corrective proposée.

Ne fournissez jamais de mot de passe TYDOM, de mot de passe de compte, de jeton
d'accès, de code PIN d'alarme, d'adresse MAC complète ni de données domestiques
ou d'appareils non anonymisées. Laissez aux mainteneurs le temps de confirmer
le signalement et de préparer un correctif avant d'en publier les détails.

## Renforcement de la sécurité déjà appliqué

Un audit réalisé en mai 2026 a mis en évidence plusieurs faiblesses. Les
correctifs correspondants ont été réappliqués en juin 2026 après avoir été
partiellement écrasés par des fusions intermédiaires. Le code actuel comprend
les protections suivantes :

- les corps des requêtes sont sérialisés avec `json.dumps()` plutôt
  qu'assemblés par concaténation de chaînes ;
- les codes PIN d'alarme, les identifiants cloud et les corps de requêtes
  contenant des informations sensibles ne sont pas inscrits tels quels dans
  les journaux ;
- la vérification des certificats TLS est obligatoire pour les connexions
  cloud à `mediation.tydom.com`, tandis que l'exception explicitement
  documentée reste nécessaire pour les certificats autosignés des passerelles
  locales ;
- les valeurs insérées dans les chemins WebSocket sont encodées pour les URL ;
- les traces d'exception du flux de configuration sont gérées par la
  journalisation de Home Assistant plutôt qu'imprimées directement sur la
  sortie standard ;
- les erreurs de saisie de l'hôte, de l'adresse MAC, de l'adresse électronique
  et des zones d'alarme sont journalisées sans reproduire la valeur fournie ;
- le format des adresses MAC et électroniques fait l'objet d'une validation
  plus stricte ;
- les fichiers de trace de débogage utilisent un gestionnaire de contexte et
  un chemin de configuration Home Assistant paramétrable.

Ces protections proviennent du commit `db71301`. Elles ont d'abord été
réappliquées dans le commit `a47f338`, puis une seconde fois après le rebase de
la v0.21. Cette section remplace les anciennes notes d'audit datées et constitue
désormais le document de référence maintenu.

## Risque résiduel connu

L'authentification Digest locale de TYDOM repose toujours sur un détail
d'implémentation interne de `requests` (`HTTPDigestAuth._thread_local`). Son
remplacement nécessite une réécriture plus importante de l'authentification,
car le client asynchrone employé par l'intégration ne fournit pas directement
une authentification Digest équivalente.

La vérification TLS stricte peut également refuser un proxy d'interception dont
le certificat n'est pas approuvé par l'hôte Home Assistant. Il s'agit du
comportement sécurisé attendu et non d'une raison pour désactiver la
vérification.
