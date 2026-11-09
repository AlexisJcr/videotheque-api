from flask import Flask, jsonify, request
import json
import os
import threading
from datetime import datetime, timedelta

app = Flask(__name__)
DATA_FILE = 'videotheque.json'

# Création d'un locker pour sécuriser les écritures dans le fichier JSON
file_lock = threading.Lock()

def lire_donnees():
    """Fonction utilitaire pour lire le fichier JSON."""
    if not os.path.exists(DATA_FILE):
        return {"utilisateurs": [], "films": [], "emprunts": []}
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def ecrire_donnees(data):
    """Fonction utilitaire pour sauvegarder dans le fichier JSON."""
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# =======================
# === Système de logs ===
# =======================
def enregistrer_log(categorie, action, details, auteur="Système"):
    """Enregistre un événement horodaté dans la base JSON (doit être appelée sous file_lock)."""
    data = lire_donnees()
    logs = data.setdefault("logs", [])
    nouvel_id = 1 if not logs else max(l.get("id", 0) for l in logs) + 1
    
    entree_log = {
        "id": nouvel_id,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "categorie": categorie,   # FILM, SUPPORT, EMPRUNT, AUTH
        "action": action,         # AJOUT, MODIFICATION, SUPPRESSION, EMPRUNT, RETOUR, LOGIN, LOGOUT
        "details": details,
        "auteur": auteur
    }
    logs.append(entree_log)
    ecrire_donnees(data)

@app.route('/api/films', methods=['GET'])
def get_films():
    """Récupère tout le catalogue."""
    data = lire_donnees()
    return jsonify(data.get("films", [])), 200

@app.route('/api/films/<int:film_id>', methods=['GET'])
def get_film_by_id(film_id):
    """Récupère les détails d'un seul film."""
    data = lire_donnees()
    film = next((f for f in data.get("films", []) if f["id"] == film_id), None)
    
    if film:
        return jsonify(film), 200
    return jsonify({"erreur": "Film introuvable"}), 404

# =======================
# === Ajout d'un film ===
# =======================
@app.route('/api/films', methods=['POST'])
def ajouter_film():
    """Ajoute un nouveau film au catalogue."""
    nouveau_film = request.get_json()
    
    # Validation basique
    if not nouveau_film or 'titre' not in nouveau_film:
        return jsonify({"erreur": "Données invalides, titre manquant"}), 400

    # DEBUT DE LA SECTION ATOMIQUE
    with file_lock:
        data = lire_donnees()
        films = data.get("films", [])
        
        # Génération d'un nouvel ID 
        nouvel_id = 1 if not films else max(f["id"] for f in films) + 1
        nouveau_film["id"] = nouvel_id
        
        # Ajout et sauvegarde
        films.append(nouveau_film)
        data["films"] = films
        ecrire_donnees(data)
        enregistrer_log("FILM", "AJOUT", f"Création du film '{nouveau_film.get('titre')}' (ID: {nouvel_id})")
    # FIN DE LA SECTION ATOMIQUE (le locker se libère automatiquement)
    
    # 201 = Created (Code HTTP standard pour une création réussie)
    return jsonify({"message": "Film ajouté avec succès", "id": nouvel_id}), 201


# ==============================
# === Modification d'un film ===
# ==============================
@app.route('/api/films/<int:film_id>', methods=['PUT'])
def modifier_film(film_id):
    """Modifie les informations d'un film existant."""
    donnees_maj = request.get_json()
    
    with file_lock:
        data = lire_donnees()
        films = data.get("films", [])
        film_index = next((index for (index, f) in enumerate(films) if f["id"] == film_id), None)
        
        if film_index is None:
            return jsonify({"erreur": "Film introuvable"}), 404
            
        # Mise à jour des champs (on conserve l'existant si la donnée n'est pas fournie)
        film_existant = films[film_index]
        film_existant["titre"] = donnees_maj.get("titre", film_existant.get("titre"))
        film_existant["realisateur"] = donnees_maj.get("realisateur", film_existant.get("realisateur"))
        film_existant["annee"] = donnees_maj.get("annee", film_existant.get("annee"))
        film_existant["genre"] = donnees_maj.get("genre", film_existant.get("genre"))
        film_existant["synopsis"] = donnees_maj.get("synopsis", film_existant.get("synopsis"))
        
        # Mise à jour spécifique de la disponibilité numérique
        if "supports" in donnees_maj and "numerique" in donnees_maj["supports"]:
            film_existant.setdefault("supports", {}).setdefault("numerique", {})["disponible"] = donnees_maj["supports"]["numerique"].get("disponible")
        
        films[film_index] = film_existant
        ecrire_donnees(data)
        enregistrer_log("FILM", "MODIFICATION", f"Mise à jour des métadonnées du film '{film_existant.get('titre')}' (ID: {film_id})")
        
    return jsonify({"message": "Film modifié avec succès", "film": film_existant}), 200


# ============================
# === Suppression d'un film ===
# ============================
@app.route('/api/films/<int:film_id>', methods=['DELETE'])
def supprimer_film(film_id):
    """Supprime un film du catalogue."""
    with file_lock:
        data = lire_donnees()
        films = data.get("films", [])
        film_a_supprimer = next((f for f in films if f["id"] == film_id), None)
        
        if not film_a_supprimer:
            return jsonify({"erreur": "Film introuvable"}), 404
            
        # On filtre la liste pour exclure le film à supprimer
        data["films"] = [f for f in films if f["id"] != film_id]
        ecrire_donnees(data)
        enregistrer_log("FILM", "SUPPRESSION", f"Suppression du film '{film_a_supprimer.get('titre')}' (ID: {film_id})")
        
    return jsonify({"message": "Film supprimé avec succès"}), 200



# =============================
# === Ajout d'un exemplaire ===
# =============================
@app.route('/api/films/<int:film_id>/supports', methods=['POST'])
def ajouter_support(film_id):
    """Ajoute un exemplaire physique (DVD/Blu-ray) au stock d'un film."""
    nouveau_support = request.get_json()
    
    with file_lock:
        data = lire_donnees()
        films = data.get("films", [])
        film_index = next((index for (index, f) in enumerate(films) if f["id"] == film_id), None)
        
        if film_index is None:
            return jsonify({"erreur": "Film introuvable"}), 404
            
        # On s'assure que la liste 'physiques' existe
        film = films[film_index]
        if "physiques" not in film.get("supports", {}):
            film.setdefault("supports", {})["physiques"] = []
            
        # L'état par défaut à l'entrée en stock est toujours DISPONIBLE
        nouveau_support["etat"] = "DISPONIBLE"
        film["supports"]["physiques"].append(nouveau_support)
        
        ecrire_donnees(data)
        enregistrer_log("SUPPORT", "AJOUT", f"Ajout de l'exemplaire {nouveau_support.get('supportId')} ({nouveau_support.get('format')}) pour le film ID {film_id}")
        
    return jsonify({"message": "Exemplaire ajouté au stock"}), 201


# ====================================
# === Modification d'un exemplaire ===
# ====================================
@app.route('/api/films/<int:film_id>/supports/<support_id>', methods=['PUT'])
def modifier_support_unitaire(film_id, support_id):
    """Modifie un exemplaire physique spécifique (ex: changer l'état ou le format)."""
    donnees_maj = request.get_json()
    with file_lock:
        data = lire_donnees()
        films = data.get("films", [])
        film = next((f for f in films if f["id"] == film_id), None)
        
        if not film:
            return jsonify({"erreur": "Film introuvable"}), 404
            
        physiques = film.get("supports", {}).get("physiques", [])
        support = next((s for s in physiques if s["supportId"] == support_id), None)
        
        if not support:
            return jsonify({"erreur": "Support introuvable"}), 404
            
        # Mise à jour des champs
        support["format"] = donnees_maj.get("format", support.get("format"))
        support["etat"] = donnees_maj.get("etat", support.get("etat"))
        
        # Modification de l'ID si le code-barres change (et on s'assure qu'il est fourni)
        nouveau_id = donnees_maj.get("nouveau_supportId")
        if nouveau_id and nouveau_id != support_id:
            support["supportId"] = nouveau_id
            
        ecrire_donnees(data)
        enregistrer_log("SUPPORT", "MODIFICATION", f"Mise à jour du support {support_id} : État={support.get('etat')}, Format={support.get('format')}")
        
    return jsonify({"message": "Support modifié avec succès", "support": support}), 200


# ==================================
# === Supression d'un exemplaire ===
# ==================================
@app.route('/api/films/<int:film_id>/supports/<support_id>', methods=['DELETE'])
def supprimer_support_unitaire(film_id, support_id):
    """Supprime un exemplaire physique, bloqué si le support est prêté."""
    with file_lock:
        data = lire_donnees()
        films = data.get("films", [])
        film = next((f for f in films if f["id"] == film_id), None)
        
        if not film:
            return jsonify({"erreur": "Film introuvable"}), 404
            
        physiques = film.get("supports", {}).get("physiques", [])
        support = next((s for s in physiques if s["supportId"] == support_id), None)
        
        if not support:
            return jsonify({"erreur": "Support introuvable"}), 404
            
        # VÉRIFICATION DE LA RÈGLE DE GESTION : Impossible de supprimer un support prêté
        if support.get("etat") == "PRETE":
            return jsonify({"erreur": "Impossible de supprimer un support en cours de prêt"}), 403
            
        # On recrée la liste en excluant le support à supprimer
        film["supports"]["physiques"] = [s for s in physiques if s["supportId"] != support_id]
        ecrire_donnees(data)
        enregistrer_log("SUPPORT", "SUPPRESSION", f"Suppression du support {support_id} du film ID {film_id}")
        
    return jsonify({"message": "Support supprimé"}), 200



# ===============================
# === Emprunter un exemplaire ===
# ===============================
@app.route('/api/emprunt', methods=['POST'])
def emprunter_support():
    """Crée un prêt (Diagramme de Séquence : Emprunter un support)."""
    payload = request.get_json()
    support_id = payload.get("supportId")
    jeton = payload.get("jeton")

    if not support_id or not jeton:
        return jsonify({"erreur": "Données incomplètes (supportId ou jeton manquant)"}), 400

    # DÉBUT DE LA SECTION ATOMIQUE (Verrou)
    with file_lock:
        data = lire_donnees()
        utilisateurs = data.get("utilisateurs", [])
        films = data.get("films", [])
        emprunts = data.setdefault("emprunts", [])

        # 1. Vérifie le jeton (membre authentifié et actif)
        user = next((u for u in utilisateurs if u.get("jeton") == jeton and u.get("actif")), None)
        if not user:
            return jsonify({"erreur": "Non authentifié ou jeton invalide"}), 401

        # 2. Chercher le support dans tous les films
        support_trouve = None
        for film in films:
            physiques = film.get("supports", {}).get("physiques", [])
            for sup in physiques:
                if sup.get("supportId") == support_id:
                    support_trouve = sup
                    break
            if support_trouve:
                break

        if not support_trouve:
            return jsonify({"erreur": "Support inconnu"}), 404

        # 3. Contrôle de disponibilité (RG4)
        if support_trouve.get("etat") != "DISPONIBLE":
            return jsonify({"erreur": "Support indisponible (perdu ou déjà prêté)"}), 409

        # 4. Contrôle du quota de 3 prêts (RG5)
        prets_en_cours = [e for e in emprunts if e.get("utilisateur_id") == user["id"] and e.get("statut") == "EN_COURS"]
        quota_max = user.get("quota_max", 3)
        if len(prets_en_cours) >= quota_max:
            return jsonify({"erreur": f"Limite de {quota_max} prêts en cours atteinte"}), 403

        # 5. Emprunt possible : Création du prêt (J+14)
        date_debut = datetime.now()
        date_retour = date_debut + timedelta(days=14)
        
        nouvel_id_emprunt = 1 if not emprunts else max(e.get("id_emprunt", 0) for e in emprunts) + 1
        
        nouveau_pret = {
            "id_emprunt": nouvel_id_emprunt,
            "utilisateur_id": user["id"],
            "supportId": support_id,
            "date_debut": date_debut.strftime("%Y-%m-%d"),
            "date_retour_prevue": date_retour.strftime("%Y-%m-%d"),
            "statut": "EN_COURS"
        }
        
        emprunts.append(nouveau_pret)
        support_trouve["etat"] = "PRETE"
        
        ecrire_donnees(data)
        enregistrer_log("EMPRUNT", "EMPRUNT", f"Emprunt du support {support_id} par l'utilisateur {user.get('nom')} (ID: {user.get('id')}). Prévu le {nouveau_pret['date_retour_prevue']}", auteur=user.get('nom'))
        
    return jsonify({"message": "Emprunt validé", "date_retour_prevue": nouveau_pret["date_retour_prevue"]}), 201


# ==============================
# === Retour d'un exemplaire ===
# ==============================
@app.route('/api/retour', methods=['POST'])
def restituer_support():
    """Clôture un prêt en cours et rend le support disponible."""
    payload = request.get_json()
    support_id = payload.get("supportId")

    with file_lock:
        data = lire_donnees()
        films = data.get("films", [])
        emprunts = data.get("emprunts", [])

        # 1. Chercher le support physique
        support_trouve = None
        for film in films:
            physiques = film.get("supports", {}).get("physiques", [])
            for sup in physiques:
                if sup.get("supportId") == support_id:
                    support_trouve = sup
                    break
            if support_trouve:
                break
                
        if not support_trouve:
            return jsonify({"erreur": "Support introuvable"}), 404

        # 2. Chercher le prêt actif lié à ce support
        pret_en_cours = next((e for e in emprunts if e.get("supportId") == support_id and e.get("statut") == "EN_COURS"), None)
        
        if not pret_en_cours:
            return jsonify({"erreur": "Aucun prêt en cours trouvé pour ce support"}), 404

        # 3. Mises à jour
        pret_en_cours["statut"] = "TERMINE"
        support_trouve["etat"] = "DISPONIBLE"
        
        ecrire_donnees(data)
        enregistrer_log("EMPRUNT", "RETOUR", f"Restitution du support {support_id} (Prêt ID: {pret_en_cours.get('id_emprunt')})")

    return jsonify({"message": "Support restitué avec succès"}), 200


# =======================
# === Système de logs ===
# =======================
@app.route('/api/logs', methods=['GET'])
def get_logs():
    """Récupère l'historique complet des logs, trié du plus récent au plus ancien."""
    data = lire_donnees()
    logs = data.get("logs", [])
    # Tri décroissant par date/ID
    logs_tries = sorted(logs, key=lambda x: x.get("id", 0), reverse=True)
    return jsonify(logs_tries), 200

@app.route('/api/logs', methods=['POST'])
def creer_log_externe():
    """Permet au tiers présentation de journaliser des événements (ex: auth)."""
    payload = request.get_json() or {}
    with file_lock:
        enregistrer_log(
            categorie=payload.get("categorie", "APPLICATION"),
            action=payload.get("action", "ACTION"),
            details=payload.get("details", ""),
            auteur=payload.get("auteur", "Visiteur")
        )
    return jsonify({"message": "Log enregistré"}), 201

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)