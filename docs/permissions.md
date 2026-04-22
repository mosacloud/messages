# Permissions & Abilities

Documentation de la logique d'autorisation dans Messages : modèle de données, rôles, mécanismes techniques, matrice des droits par ressource et état des lieux.

> Public visé : développeur·euse backend intervenant sur l'API REST ou sur le domaine d'accès.

---

## 1. Concepts fondamentaux

### 1.1 Modèle à deux niveaux

Messages applique une autorisation à deux niveaux, indépendants mais composés :

```
Utilisateur ──(MailboxAccess)──▶ Mailbox ──(ThreadAccess)──▶ Thread
                                     │
                                     └──(possède)──▶ Label, Contact, Channel…

Utilisateur ──(MailDomainAccess)──▶ MailDomain ──(possède)──▶ Mailbox
```

- **`MailboxAccess`** : rôle de l'utilisateur **sur une BAL** (boîte aux lettres). Porte les rôles `VIEWER`, `EDITOR`, `SENDER`, `ADMIN`.
- **`ThreadAccess`** : rôle d'une **BAL sur un fil**. Porte les rôles `VIEWER`, `EDITOR`. C'est ce qui permet de partager un fil à plusieurs BAL avec des niveaux différents.
- **`MailDomainAccess`** : rôle (unique : `ADMIN`) d'un utilisateur sur un domaine de messagerie.

Cette séparation est volontaire : un utilisateur `SENDER` sur une BAL dispose des droits d'envoi pour cette BAL, mais si cette BAL n'a qu'un accès `VIEWER` sur un fil donné, l'utilisateur ne peut pas en modifier l'état partagé. C'est la source de vérité portée par le queryset `ThreadAccess.objects.editable_by(user)` (voir §3.4).

### 1.2 Règle d'or des « droits d'édition pleins » sur un fil

Pour **muter l'état partagé** d'un fil (archiver, corbeille, spam, labels, événements non-IM, partage), il faut **cumulativement** :

1. `ThreadAccess.role == EDITOR` sur une mailbox partagée du fil ;
2. `MailboxAccess.role ∈ {EDITOR, SENDER, ADMIN}` sur cette même mailbox.

Cette contrainte évite qu'un `VIEWER` sur une BAL collective puisse muter un fil auquel la BAL a pourtant un `EDITOR` ThreadAccess.

### 1.3 Actions personnelles vs actions partagées

Certaines actions ne modifient **que l'état personnel** de l'utilisateur et sont autorisées aux `VIEWER` :

| Action personnelle | Donnée mutée | Accès minimum |
|---|---|---|
| Marquer lu / non lu | `ThreadAccess.read_at` | `MailboxAccess` quelconque |
| Starred / unstarred | `ThreadAccess.starred_at` | `MailboxAccess` quelconque |
| Lire une mention | `UserEvent.read_at` (pour soi) | Accès au fil |
| Poster un commentaire interne (`IM`) | Nouveau `ThreadEvent` | `ThreadAccess` + `MailboxAccess` au moins `EDITOR` sur la BAL |

Les flags de message (`trashed`, `archived`, `spam`) sont au contraire un **état partagé** et exigent les droits d'édition pleins.

---

## 2. Rôles et enums

Les enums sont définis dans `src/backend/core/enums.py`.

### 2.1 `MailboxRoleChoices` (utilisateur → BAL)

| Valeur | Nom | Portée |
|-------:|-----|--------|
| 1 | `VIEWER` | Lecture des fils et messages |
| 2 | `EDITOR` | Création/édition de drafts, labels, flags partagés, gestion partage |
| 3 | `SENDER` | `EDITOR` + envoi des messages |
| 4 | `ADMIN` | `SENDER` + gestion des accès, templates, import |

Groupes pré-calculés :

- `MAILBOX_ROLES_CAN_EDIT = [EDITOR, SENDER, ADMIN]`
- `MAILBOX_ROLES_CAN_SEND = [SENDER, ADMIN]`

> ⚠️ Les comparaisons numériques (`role >= EDITOR`) sont utilisées dans `Mailbox.get_abilities()`. Elles reposent sur le fait que la hiérarchie est strictement inclusive — toute nouvelle valeur intermédiaire casserait cette invariante.

### 2.2 `ThreadAccessRoleChoices` (BAL → fil)

| Valeur | Nom |
|-------:|-----|
| 1 | `VIEWER` |
| 2 | `EDITOR` |

### 2.3 `MailDomainAccessRoleChoices`

Un seul rôle : `ADMIN` (valeur 1).

### 2.4 Abilities exposées dans l'API

Les abilities sont des **clés plates** que l'API renvoie dans les serializers afin que le frontend masque ou grise les actions non autorisées.

- `UserAbilities` : `view_maildomains`, `create_maildomains`, `manage_maildomain_accesses`
- `CRUDAbilities` : `get`, `post`, `put`, `patch`, `delete`
- `MailDomainAbilities` : `manage_accesses`, `manage_mailboxes`
- `MailboxAbilities` : `manage_accesses`, `view_messages`, `send_messages`, `manage_labels`, `manage_message_templates`, `import_messages`
- `ThreadAbilities` : `edit`

> Les modèles `ThreadAccess`, `Message`, `Label`, `ThreadEvent`, `UserEvent` n'ont **pas** de `get_abilities()` et n'émettent donc pas de clé `abilities` dans leur payload. Voir §5 — c'est un des points de l'état des lieux.

---

## 3. Mécanismes techniques

### 3.1 Couches impliquées

| Couche | Fichier | Rôle |
|---|---|---|
| Classes de permission DRF | `src/backend/core/api/permissions.py` | Gate d'accès (HTTP) avant l'exécution de la vue |
| Méthodes `get_abilities()` | `src/backend/core/models.py` | Calcul des droits d'un utilisateur sur une instance |
| `AbilitiesModelSerializer` | `src/backend/core/api/serializers.py` | Injection automatique du champ `abilities` dans la sortie JSON |
| QuerySet `editable_by` | `ThreadAccessQuerySet` (`models.py`) | Source de vérité SQL pour « full edit rights » |
| Annotations viewsets | `ThreadViewSet._annotate_thread_permissions` | Calcul en masse via subqueries (`_can_edit`, `_has_unread`, `_has_starred`, `_has_mention`…) |

### 3.2 Classes de permission DRF

| Classe | Portée | Utilisée par |
|---|---|---|
| `IsAuthenticated` | Vérifie `request.auth` ou `request.user.is_authenticated` | Quasiment toutes les vues |
| `IsSuperUser` | `user.is_superuser` uniquement | `AdminMailDomainViewSet.create`, `UserViewSet.list` |
| `IsSelf` | `obj == request.user` | `UserViewSet.get_me` |
| `IsAllowedToAccess` | Accès à une BAL / un fil / un message selon contexte URL et action | `MessageViewSet`, `ThreadEventViewSet` (lecture), `ChangeFlagView`, `SendMessageView` |
| `IsAllowedToCreateMessage` | Droits `EDITOR+` sur la BAL émettrice et accès au fil parent/draft | `DraftMessageView` |
| `IsAllowedToManageThreadAccess` | Droits d'édition pleins sur le fil, URL `thread_id` obligatoire | `ThreadAccessViewSet` |
| `HasThreadEditAccess` | Droits d'édition pleins sur le fil (via `editable_by`) | Actions `destroy`, `split`, `refresh_summary` de `ThreadViewSet` |
| `HasThreadEventWriteAccess` | Écriture sur `ThreadEvent`, règle **dépend du type** (voir §4.1) | Actions d'écriture de `ThreadEventViewSet` |
| `HasThreadCommentAccess` | Auteur possible d'un commentaire interne | `ThreadUserViewSet` (lister les mentionnables) |
| `IsMailDomainAdmin` | `MailDomainAccess.role == ADMIN` sur le `maildomain_pk` URL | Administration de domaine (nested routers) |
| `IsMailboxAdmin` | `ADMIN` sur la mailbox ou sur son domaine, ou superuser | `MailboxAccessViewSet` |
| `HasAccessToMailbox` | Existence d'un `MailboxAccess` sur `mailbox_id` URL | `ChannelViewSet` (BAL) |
| `HasChannelScope` + `channel_scope(...)` | Scope d'un token `Channel` (api_key) | Endpoints appelés par des intégrations (webhook, widget, mta) |
| `IsGlobalChannelMixin` | Renforce que le `Channel` est `scope_level=global` | Endpoints globaux (metrics, création de domaine) |
| `DenyAll` | Refuse systématiquement | Désactivation conditionnelle par feature flag |

### 3.3 `get_abilities()` et `AbilitiesModelSerializer`

Les serializers qui héritent de `AbilitiesModelSerializer` injectent automatiquement un champ `abilities` dont la valeur est le résultat de `instance.get_abilities(request.user)`.

```python
class AbilitiesModelSerializer(serializers.ModelSerializer):
    def __init__(self, *args, **kwargs):
        ...
        if not self.exclude_abilities:
            self.fields["abilities"] = serializers.SerializerMethodField(read_only=True)

    def get_abilities(self, instance):
        request = self.context.get("request")
        if not request:
            return {}
        if isinstance(instance, models.User):
            return instance.get_abilities()
        return instance.get_abilities(request.user)
```

Cela permet au frontend de lire les droits côté réponse API **sans refaire lui-même de logique** et de masquer les boutons non autorisés.

### 3.4 QuerySet `ThreadAccess.objects.editable_by(user, mailbox_id=None)`

Source de vérité SQL pour « qui peut éditer ce fil ». Applique les deux conditions obligatoires **dans le même `.filter()`** (sinon Django génère deux jointures indépendantes et matche des paires d'accès incorrectes — noté dans le code) :

```python
qs = self.filter(
    role=ThreadAccessRoleChoices.EDITOR,
    mailbox__accesses__user=user,
    mailbox__accesses__role__in=MAILBOX_ROLES_CAN_EDIT,
)
```

Consommé par : `HasThreadEditAccess`, `HasThreadEventWriteAccess`, `ChangeFlagView`, `Thread.get_abilities`, `ThreadViewSet._annotate_thread_permissions` (via subquery).

---

## 4. Règles particulières

### 4.1 Événements de fil (`ThreadEvent`)

Trois types d'événements : `im` (message interne / commentaire), `assign`, `unassign`. La gate d'écriture dépend du type (`HasThreadEventWriteAccess`) :

| Type | Création | Update / Destroy |
|---|---|---|
| `im` | `MailboxAccess ∈ {EDITOR, SENDER, ADMIN}` + **n'importe quel** `ThreadAccess` | Mêmes droits + **doit être l'auteur** + **dans la fenêtre d'édition** (`settings.MAX_THREAD_EVENT_EDIT_DELAY`) |
| `assign` / `unassign` | Droits d'édition pleins (`editable_by`) | Droits d'édition pleins + auteur + fenêtre d'édition |

La fenêtre d'édition (`is_editable()`) est vérifiée dans `ThreadEventViewSet.perform_update` / `perform_destroy`. Une valeur `0` désactive la limitation.

Les créations `assign` / `unassign` sont **idempotentes** : `ThreadEventViewSet.create` filtre les assignés déjà existants pour éviter de créer un événement vide.

### 4.2 Mentions et `UserEvent`

`UserEvent` n'a **pas** de ViewSet dédié ni de permission class propre. Il est créé par des signaux (`src/backend/core/signals.py`) à partir d'un `ThreadEvent` de type `im` contenant des mentions ou `assign`/`unassign`.

- **Lecture des mentions** : exposée comme annotation (`_has_unread_mention`, `_has_mention`) dans `ThreadViewSet` et comme champ de `ThreadEventSerializer`. Requête implicite : le propriétaire lit ses propres `UserEvent` via les filtres sur le user courant.
- **Acquittement** : action custom `ThreadEventViewSet.read_mention` (PATCH `threads/{id}/events/{id}/read-mention/`). Requiert `IsAllowedToAccess` (lecture du fil). Met à jour uniquement les `UserEvent` du user courant → idempotent.

### 4.3 Flags de fil (`ChangeFlagView`)

Endpoint : `POST /api/v1.0/flag/`. Permission : `IsAllowedToAccess` (authentifié). La logique d'accès par flag est réalisée **dans la vue** :

| Flag | Queryset filtrant l'accès | Intention |
|---|---|---|
| `unread`, `starred` | `ThreadAccess.objects.filter(mailbox__accesses__user=user)` | Action personnelle → `VIEWER` suffit |
| `trashed`, `archived`, `spam` | `ThreadAccess.objects.editable_by(user)` | État partagé → droits d'édition pleins |

### 4.4 Labels

Un label appartient à une **seule BAL**. Le droit `manage_labels` est porté par `Mailbox.get_abilities()` (valeur = `can_modify`, donc `EDITOR+`).

Attacher / détacher un label à un fil (`/labels/{id}/add-threads/`) requiert :
- `MailboxAccess ∈ {EDITOR, SENDER, ADMIN}` sur la BAL du label ;
- que le fil cible appartienne à la BAL du label (pas besoin d'être `EDITOR` sur le fil lui-même — commentaire explicite dans `label.py:294-301`).

Cette règle a été un choix conscient : le label est un outil d'organisation **local** à la BAL.

### 4.5 Brouillons et envoi

- `DraftMessageView` : `IsAllowedToCreateMessage` vérifie `senderId` + `MailboxAccess ∈ MAILBOX_ROLES_CAN_EDIT`. Pour les réponses, exige un `ThreadAccess.EDITOR` entre la mailbox et le fil parent. Pour l'update, exige idem sur la mailbox et le fil du draft.
- `SendMessageView` : `IsAllowedToAccess` + vérification explicite dans la vue que la mailbox émettrice est bien un `ThreadAccess` du fil (jointure au fetch). Ne vérifie pas explicitement `MAILBOX_ROLES_CAN_SEND` — la gate réelle est sur `MailboxAccess` des mailboxes concernées via `IsAllowedToAccess.has_object_permission` (branche `view.action == "send"` → `MAILBOX_ROLES_CAN_SEND`).

---

## 5. Matrice des droits

Légende des colonnes :
- `U-SU` : superuser ;
- `U-MD-ADMIN` : admin du `MailDomain` ;
- `M-A/S/E/V` : `MailboxAccess` ADMIN / SENDER / EDITOR / VIEWER ;
- `T-E/V` : `ThreadAccess` EDITOR / VIEWER ;
- Dans la matrice : ✅ autorisé, ⚠️ autorisé sous condition additionnelle, ❌ refusé, — non applicable.

### 5.1 `MailDomain`

Défini dans `MailDomain.get_abilities(user)` (`models.py:364`) et les permissions `AdminMailDomainViewSet`.

| Action | Endpoint | Superuser | `U-MD-ADMIN` | Autres |
|---|---|:-:|:-:|:-:|
| Lister les domaines dont l'user a un accès | `GET /maildomains/` | ✅ | ✅ | ❌ |
| Voir un domaine | `GET /maildomains/{id}/` | ✅ | ✅ | ❌ |
| Créer un domaine | `POST /maildomains/` | ⚠️ feature flag `FEATURE_MAILDOMAIN_CREATE` | ❌ | ❌ |
| Mettre à jour / supprimer | ❌ non exposé via API | — | — | — |
| Gérer les accès du domaine | Ability `manage_accesses` | ✅ | ✅ | ❌ |
| Gérer les BALs du domaine | Ability `manage_mailboxes` | ✅ | ✅ | ❌ |
| Vérification DNS | `GET /maildomains/{id}/check-dns/` | ✅ | ✅ | ❌ |

### 5.2 `MailDomainAccess`

`MaildomainAccessViewSet` — permissions `IsSuperUser | IsMailDomainAdmin`.

| Action | Superuser | `U-MD-ADMIN` | Autres | Notes |
|---|:-:|:-:|:-:|---|
| Lister | ✅ | ✅ | ❌ | |
| Lire | ✅ | ✅ | ❌ | |
| Créer | ⚠️ | ⚠️ | ❌ | Gated par `FEATURE_MAILDOMAIN_MANAGE_ACCESSES` |
| Supprimer | ⚠️ | ⚠️ | ❌ | Idem |
| Modifier | — | — | — | Pas de `UpdateModelMixin` (rôle unique `ADMIN`) |

### 5.3 `Mailbox`

Défini dans `Mailbox.get_abilities(user)` (`models.py:778`). Accès via `MailboxViewSet` + feature flags.

| Ability | `M-A` | `M-S` | `M-E` | `M-V` | Aucun |
|---|:-:|:-:|:-:|:-:|:-:|
| `get` (lire la BAL) | ✅ | ✅ | ✅ | ✅ | ❌ |
| `post` / `patch` / `put` (créer/modifier) | ✅ | ✅ | ✅ | ❌ | ❌ |
| `delete` | ✅ | ❌ | ❌ | ❌ | ❌ |
| `manage_accesses` | ✅ | ❌ | ❌ | ❌ | ❌ |
| `view_messages` | ✅ | ✅ | ✅ | ✅ | ❌ |
| `send_messages` | ✅ | ✅ | ❌ | ❌ | ❌ |
| `manage_labels` | ✅ | ✅ | ✅ | ❌ | ❌ |
| `manage_message_templates` | ⚠️ flag | ❌ | ❌ | ❌ | ❌ |
| `import_messages` | ⚠️ flag | ❌ | ❌ | ❌ | ❌ |

> Les flags `FEATURE_MESSAGE_TEMPLATES` et `FEATURE_IMPORT_MESSAGES` basculent les abilities à `False` quel que soit le rôle.

### 5.4 `MailboxAccess`

`MailboxAccessViewSet` sous `/mailboxes/{id}/accesses/`. Permission : `IsMailboxAdmin` (ADMIN de la BAL ou de son domaine, ou superuser).

| Action | `M-A` sur cible | `U-MD-ADMIN` du domaine | Superuser | Autres |
|---|:-:|:-:|:-:|:-:|
| Lister / Lire | ✅ | ✅ | ✅ | ❌ |
| Créer | ✅ | ✅ | ✅ | ❌ |
| Modifier le rôle | ✅ | ✅ | ✅ | ❌ |
| Supprimer | ✅ | ✅ | ✅ | ❌ |

### 5.5 `Thread`

`ThreadViewSet`. Permission par défaut : `IsAuthenticated`. Les abilities (`ThreadAbilities.CAN_EDIT`) sont exposées via `ThreadSerializer.get_abilities`.

| Action | Endpoint | `T-E` + `M-CAN_EDIT` | `T-V` ou `M-V` | Aucun accès |
|---|---|:-:|:-:|:-:|
| Lister les fils accessibles | `GET /threads/` | ✅ | ✅ | ❌ |
| Lire un fil | `GET /threads/{id}/` | ✅ | ✅ | ❌ |
| Supprimer un fil | `DELETE /threads/{id}/` | ✅ | ❌ | ❌ |
| Scinder un fil | `POST /threads/{id}/split/` | ✅ | ❌ | ❌ |
| Rafraîchir le résumé IA | `POST /threads/{id}/refresh-summary/` | ✅ | ❌ | ❌ |
| Stats agrégées | `GET /threads/stats/` | ✅ | ✅ | ❌ |

> L'appartenance au fil est calculée via `ThreadAccess` : une BAL dont l'user a un `MailboxAccess` quelconque suffit pour la lecture.

### 5.6 `ThreadAccess`

`ThreadAccessViewSet` sous `/threads/{thread_id}/accesses/`. Permission : `IsAllowedToManageThreadAccess`.

| Action | `T-E` + `M-CAN_EDIT` | `T-V` + `M-CAN_EDIT` | `M-V` | Aucun |
|---|:-:|:-:|:-:|:-:|
| Lister les accesses du fil | ✅ | ❌ | ❌ | ❌ |
| Créer un access (partager) | ✅ | ❌ | ❌ | ❌ |
| Mettre à jour (changer le rôle) | ✅ | ❌ | ❌ | ❌ |
| Supprimer son propre access | ⚠️ voir note | ⚠️ voir note | ❌ | ❌ |

> **Note supprimer** : `destroy` est permis si l'utilisateur est `M-CAN_EDIT` sur la BAL concernée (*y compris sans EDITOR sur le fil*), pour autoriser une BAL à se retirer du fil. Une garde empêche la suppression du **dernier** EDITOR d'un fil (`perform_destroy` avec verrou `SELECT FOR UPDATE`).

### 5.7 `Message`

`MessageViewSet` + `ChangeFlagView` + `SendMessageView` + `DraftMessageView`.

| Action | Endpoint | `T-E` + `M-CAN_EDIT` | `T-V` ou `M-V` | `M-SEND` sur la BAL émettrice |
|---|---|:-:|:-:|:-:|
| Lister / Lire | `GET /messages/` | ✅ | ✅ | — |
| Télécharger EML | `GET /messages/{id}/eml/` | ✅ | ✅ | — |
| Supprimer | `DELETE /messages/{id}/` | ✅ | ❌ | — |
| Changer flags (unread, starred) | `POST /flag/` | ✅ | ✅ | — |
| Changer flags (trashed, archived, spam) | `POST /flag/` | ✅ | ❌ | — |
| Mettre à jour un statut de livraison | `PATCH /messages/{id}/delivery-statuses/` | ✅ | ❌ | ✅ requis |
| Créer / MAJ un brouillon | `POST /draft/` | ✅ (`M-CAN_EDIT` sur émettrice) | ❌ | ✅ |
| Envoyer | `POST /send/` | ✅ + `M-CAN_SEND` sur émettrice | ❌ | ✅ |

### 5.8 `Label`

`LabelViewSet`. Permission : `IsAuthenticated` + vérifications manuelles dans la vue.

| Action | `M-CAN_EDIT` sur BAL du label | `M-V` sur BAL | Aucun accès BAL |
|---|:-:|:-:|:-:|
| Lister | ✅ | ✅ (read seul) | ❌ |
| Créer | ✅ | ❌ | ❌ |
| Modifier | ✅ | ❌ | ❌ |
| Supprimer | ✅ | ❌ | ❌ |
| `add-threads` / `remove-threads` | ✅ | ❌ | ❌ |

### 5.9 `ThreadEvent`

`ThreadEventViewSet` sous `/threads/{thread_id}/events/`. Lecture : `IsAllowedToAccess`. Écriture : `HasThreadEventWriteAccess`.

| Action | Type | `T-E` + `M-CAN_EDIT` | `T-V` + `M-CAN_EDIT` | `T-E` + `M-V` | `T-V` + `M-V` ou aucun |
|---|---|:-:|:-:|:-:|:-:|
| Lister / Lire | tous | ✅ | ✅ | ✅ | ❌ |
| `read-mention` (acquittement personnel) | — | ✅ | ✅ | ✅ | ❌ |
| Créer | `im` | ✅ | ✅ | ❌ | ❌ |
| Créer | `assign` / `unassign` | ✅ | ❌ | ❌ | ❌ |
| Update / Destroy (auteur uniquement, fenêtre valide) | `im` | ✅ | ✅ | ❌ | ❌ |
| Update / Destroy (auteur uniquement, fenêtre valide) | `assign` / `unassign` | ✅ | ❌ | ❌ | ❌ |

> La vérification « auteur uniquement » est faite dans `HasThreadEventWriteAccess.has_object_permission` et `HasThreadEditAccess.has_object_permission`. La fenêtre temporelle est `settings.MAX_THREAD_EVENT_EDIT_DELAY` et est vérifiée dans `perform_update` / `perform_destroy`.

### 5.10 `UserEvent`

Pas de viewset dédié. Accès uniquement via :

| Action | Mécanisme | Droits |
|---|---|---|
| Lister mes mentions / assignations | Annotations `_has_mention`, `_has_unread_mention`, `_has_assigned_to_me`, `_has_unassigned` dans `ThreadViewSet` | Accès au fil |
| Acquitter une mention | Action `read-mention` de `ThreadEventViewSet` | Accès au fil |
| Créer | Signal `post_save` sur `ThreadEvent` (cœur, pas d'API) | — |

Conséquence : un `UserEvent` est **intrinsèquement lié à son destinataire** — il n'y a aucun endpoint permettant à un autre utilisateur d'y accéder directement.

### 5.11 `User`

`UserViewSet`.

| Action | Endpoint | Superuser | `U-MD-ADMIN` | Lui-même | Autres |
|---|---|:-:|:-:|:-:|:-:|
| `me` | `GET /users/me/` | ✅ | ✅ | ✅ | ✅ |
| Rechercher un user (≥ 3 caractères) | `GET /users/?q=...` | ✅ (global) | ✅ (scope maildomain) | — | ❌ |

---

## 6. État des lieux

### 6.1 Points forts

- **Séparation stricte à deux niveaux** (BAL ↔ Fil) : permet un partage fil-par-fil sans dupliquer la gestion des utilisateurs.
- **Source de vérité SQL unique** pour « droits d'édition pleins » : `ThreadAccess.objects.editable_by()`. Utilisée à la fois en permission class et en annotation viewset, ce qui évite les divergences.
- **Pattern `AbilitiesModelSerializer`** élégant : le frontend n'a qu'à lire le champ `abilities` pour conditionner l'UI.
- **Commentaires IM relaxés** : règle produit fine (un `VIEWER` d'un fil mais `EDITOR` de sa BAL peut poster un commentaire interne) bien encapsulée dans `HasThreadEventWriteAccess`.
- **Idempotence** sur `assign`/`unassign` et `read-mention` : gestion des doublons côté serveur, client simplifié.
- **Garde-fou « dernier EDITOR »** sur `ThreadAccess.destroy` avec verrou `SELECT FOR UPDATE` pour gérer la concurrence.
- **Feature flags DRF** (`DenyAll`) : les endpoints désactivés répondent 403 proprement plutôt qu'une 404 ambiguë.

### 6.2 Dette technique identifiée

1. **Couverture incomplète des abilities**. Les modèles `ThreadAccess`, `Message`, `Label`, `ThreadEvent`, `UserEvent` **n'ont pas** de méthode `get_abilities()`. Conséquence : le frontend doit **ré-inférer** les droits à partir des abilities du `Thread` ou de la `Mailbox`. C'est fragile dès qu'une règle évolue côté backend (ex. fenêtre d'édition de `ThreadEvent`, règle `can_modify` des labels, règle d'envoi). **Amélioration suggérée** : ajouter `get_abilities()` au moins sur `Label`, `ThreadEvent` (en exposant `can_edit`, `can_delete`, `is_editable`) et `Message` (`can_delete`, `can_send`, `can_change_flag`).

2. **Logique de permission dispersée entre trois couches**. Pour `Label`, par exemple, la logique vit simultanément dans :
   - `LabelViewSet.check_mailbox_permissions` (vérif explicite)
   - `LabelSerializer.validate_mailbox` (vérif à la création)
   - `LabelViewSet.get_object` (vérif de lecture)
   - `Mailbox.get_abilities()` (ability `manage_labels`)
   Cela rend les évolutions risquées. **Amélioration** : centraliser dans une permission class dédiée `IsAllowedToManageLabel`.

3. **Couplage fort de `IsAllowedToAccess`**. Cette classe reçoit plusieurs types d'objets (`Mailbox`, `Thread`, `Message`, `ThreadEvent`) et **hard-code les noms d'actions** (`destroy`, `send`, `delivery_statuses`). Elle mêle gate et logique métier. Symptôme typique de *god-permission*. **Amélioration** : éclater en plusieurs classes dédiées (`IsAllowedToAccessMessage`, `IsAllowedToAccessThread`, …).

4. **Duplication de la logique `editable_by` dans les permissions**. `IsAllowedToManageThreadAccess.has_permission` répète le même filtre inline que `ThreadAccess.objects.editable_by()` alors qu'elle pourrait simplement l'appeler. Idem dans `IsAllowedToAccess.has_object_permission` (branche `destroy`/`send`/`delivery_statuses`). Risque de divergence si `editable_by` évolue.

5. **Dictionnaire `ACTION_FOR_METHOD_TO_PERMISSION`** en tête de `permissions.py` référence des actions (`versions_detail`, `children`) qui **ne correspondent à aucune vue actuelle**. Vraisemblable reste d'une version antérieure du modèle de données. Candidat à la suppression.

6. **Feature flags éparpillés**. `FEATURE_MESSAGE_TEMPLATES` et `FEATURE_IMPORT_MESSAGES` sont appliqués dans `Mailbox.get_abilities()` ; `FEATURE_MAILDOMAIN_CREATE` et `FEATURE_MAILDOMAIN_MANAGE_ACCESSES` le sont dans les `get_permissions()` via `DenyAll`. Incohérence qui rend la matrice de droits plus difficile à lire. **Amélioration** : convention unique (par exemple : toujours flag côté `get_permissions`).

7. **`MailboxRoleChoices` reposant sur la comparaison numérique**. `Mailbox.get_abilities()` utilise `role >= EDITOR`. Si l'on ajoute un rôle intermédiaire entre `EDITOR` (2) et `SENDER` (3), la sémantique dérive silencieusement. **Amélioration** : préférer l'appartenance à un groupe explicite (`role in MAILBOX_ROLES_CAN_EDIT`), ce qui est d'ailleurs le style utilisé partout ailleurs.

8. **`SendMessageView` ne vérifie pas `MAILBOX_ROLES_CAN_SEND` de manière directe**. La gate repose sur `IsAllowedToAccess.has_object_permission` branche `send`. L'endpoint serait plus lisible avec une permission dédiée `CanSendFromMailbox`.

9. **Annotation `events_count`** dans `ThreadViewSet` compte **tous** les événements du fil, y compris les `assign`/`unassign` et les `im`. Pas un bug au sens strict mais la sémantique de ce compteur est ambiguë pour le frontend (un badge « 3 événements » mélangera commentaires et mouvements d'assignation).

10. **Absence de permission class pour `UserEvent`**. Tant que les seuls accès passent par des annotations limitées à `request.user`, le modèle de permission est sûr ; mais toute nouvelle exposition (ex. liste des mentions d'un user admin sur son domaine) devra réinventer la gate.

### 6.3 Risques fonctionnels / bugs suspects

- **`IsAllowedToAccess.has_permission` — branche `is_list_action=False` sur route imbriquée** : hors création, on retourne `True` sans vérifier l'appartenance, en déléguant à `has_object_permission`. C'est correct pour les actions `retrieve` / `update` / `destroy` qui transitent par `get_object()`. C'est en revanche **risqué** si une action custom est ajoutée et oublie d'appeler `self.check_object_permissions(...)`. **Mitigation conseillée** : audit systématique des `@action` custom de `ThreadEventViewSet` / `MessageViewSet`.

- **`IsMailboxAdmin.has_object_permission` : `obj.mailbox.domain` doit être non nul**. Si une `MailboxAccess` référence une mailbox sans domaine (cas dégénéré mais possible côté migration), la méthode retourne `False` → l'admin légitime est bloqué. À valider par une contrainte DB.

- **`Thread.get_abilities(user, mailbox_id=...)` retourne `{CAN_EDIT: can_edit}` sans clé `CAN_READ` ni CRUD**. Le frontend ne peut pas distinguer « je ne peux pas éditer » de « je ne peux pas lire » via cet appel seul. Acceptable tant que l'appel ne survient qu'après un accès confirmé, mais source d'ambiguïté dans le JSON de réponse.

- **`ChangeFlagView`** calcule l'ensemble `accessible_thread_ids_qs` sans le `.distinct()` habituel. Pas d'incidence sur la correction du filtre (`id__in` déduplique), mais peut générer des plans d'exécution plus coûteux qu'il n'en faut.

- **`ThreadUserViewSet`** expose la liste des utilisateurs accédant à un fil. Permission : `HasThreadCommentAccess` (= `M-CAN_EDIT` + `ThreadAccess` quelconque). Un `VIEWER` ThreadAccess qui est `EDITOR` sur sa BAL peut ainsi **énumérer** tous les autres membres. Ce n'est pas un bug (nécessaire pour le flow mention), mais à garder en tête côté confidentialité.

### 6.4 Pistes d'amélioration priorisées

| Priorité | Action | Gain |
|:-:|---|---|
| P1 | Ajouter `get_abilities()` sur `Label`, `ThreadEvent`, `Message` | Cohérence front/back, moins de logique dupliquée côté UI |
| P1 | Centraliser les vérifs `Label` dans une permission class | Lisibilité + robustesse |
| P2 | Éclater `IsAllowedToAccess` par type d'objet | Baisse de complexité cyclomatique, testabilité |
| P2 | Remplacer la logique inline `editable_by` dans `IsAllowedToManageThreadAccess` par l'appel au queryset manager | Source de vérité unique |
| P3 | Supprimer `ACTION_FOR_METHOD_TO_PERMISSION` | Nettoyage de code mort |
| P3 | Uniformiser le placement des feature flags (toujours via `get_permissions` + `DenyAll`) | Lisibilité de la matrice |
| P3 | Documenter (tests snapshot) la matrice de droits pour détecter les régressions silencieuses | Filet de sécurité |

---

## 7. Références

- `src/backend/core/api/permissions.py` — classes de permission DRF
- `src/backend/core/models.py` — modèles, `get_abilities()`, `ThreadAccessQuerySet.editable_by`
- `src/backend/core/api/serializers.py` — `AbilitiesModelSerializer`, injection du champ `abilities`
- `src/backend/core/api/viewsets/` — gates par viewset
- `src/backend/core/enums.py` — rôles, groupes de rôles, abilities
- `src/backend/core/urls.py` — routing des viewsets
- `src/backend/core/signals.py` — création automatique de `UserEvent` à partir d'un `ThreadEvent`
