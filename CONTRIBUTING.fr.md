# Contribuer

[English](CONTRIBUTING.md) | **Français**

Les contributions sont les bienvenues, qu'il s'agisse de signalements de
bogues, d'améliorations de la documentation, de la prise en charge de nouveaux
appareils ou de corrections du comportement existant.

## Signaler un problème

Utilisez les [tickets GitHub](../../issues) pour signaler un bogue reproductible
ou proposer une fonctionnalité. Avant d'ouvrir un ticket, recherchez les
tickets existants, ouverts comme fermés, puis fournissez les informations
demandées dans le modèle correspondant.

Ne divulguez pas une vulnérabilité de sécurité dans un ticket public. Suivez
plutôt la procédure de signalement privé décrite dans la
[politique de sécurité](SECURITY.fr.md).

## Pull requests

1. Créez un fork du dépôt, puis une branche ciblée à partir de `main`.
2. Placez les corrections sans rapport entre elles dans des pull requests
   distinctes.
3. Ajoutez ou adaptez les tests lorsque cela est possible.
4. Exécutez les contrôles de qualité et de formatage.
5. Testez la modification avec le matériel Delta Dore concerné lorsque cela
   est possible.
6. Mettez la documentation à jour. Si la modification concerne le README,
   actualisez `README.md` et `README.fr.md`.
7. Ouvrez une pull request et complétez sa liste de vérification.

Décrivez le comportement observé, la modification proposée et les tests
effectués. Avant de joindre des journaux, supprimez les identifiants, codes PIN,
jetons, adresses MAC et autres informations personnelles.

## Qualité du code

Le workflow d'intégration continue utilise Ruff. Exécutez les mêmes contrôles
localement :

```bash
python3 -m pip install -r requirements.txt
python3 -m ruff check custom_components/
python3 -m ruff format custom_components/ --check
```

Exécutez dans votre environnement de développement les tests correspondant à
votre modification. Tout nouveau comportement du protocole ou d'une entité
devrait normalement être accompagné d'un test de non-régression dans `tests/`.
Pour les modifications dépendant du matériel, joignez des journaux anonymisés
et indiquez l'appareil ainsi que les opérations testées.

## Licence

En contribuant, vous acceptez que votre contribution soit publiée sous la
[licence MIT](LICENSE) du dépôt.
