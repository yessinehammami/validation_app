"""Génère le bloc à coller dans les secrets pour un nouvel utilisateur.

Usage : python creer_utilisateur.py
"""
import getpass

import streamlit_authenticator as stauth

username = input("Identifiant : ").strip().lower()
name = input("Nom affiché : ").strip()
password = getpass.getpass("Mot de passe (3 caractères min.) : ")

if len(password) < 3:
    raise SystemExit("Mot de passe trop court.")
if password != getpass.getpass("Confirmer : "):
    raise SystemExit("Les mots de passe ne correspondent pas.")

print("\nA coller dans les secrets :\n")
print(f"[credentials.usernames.{username}]")
print(f'name = "{name}"')
print(f'password = "{stauth.Hasher.hash(password)}"')
