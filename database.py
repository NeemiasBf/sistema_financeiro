import sqlite3
import os

DB_NAME = "financeiro.db"

def conectar():
    return sqlite3.connect(DB_NAME)

def criar_tabelas():
    conn = conectar()
    cursor = conn.cursor()
    
    # Tabela de Perfis (Empresas / Pessoas)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS perfis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            tipo TEXT NOT NULL,
            moeda TEXT NOT NULL,
            documento TEXT
        )
    """)
    
    # Tabela de Contas Bancárias
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS contas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            perfil_id INTEGER,
            nome TEXT NOT NULL,
            tipo TEXT NOT NULL,
            saldo_inicial REAL DEFAULT 0.0,
            FOREIGN KEY (perfil_id) REFERENCES perfis(id)
        )
    """)
    
    # Tabela de Movimentações (Receitas e Despesas)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS movimentacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            perfil_id INTEGER,
            conta_id INTEGER,
            descricao TEXT NOT NULL,
            cliente TEXT DEFAULT '',
            categoria TEXT NOT NULL,
            tipo TEXT NOT NULL,
            status TEXT NOT NULL,
            valor REAL NOT NULL,
            data_vencimento TEXT NOT NULL,
            data_pagamento TEXT,
            grupo_id TEXT,
            FOREIGN KEY (perfil_id) REFERENCES perfis(id),
            FOREIGN KEY (conta_id) REFERENCES contas(id)
        )
    """)

    # Tabela de Documentos e Anexos
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS documentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            perfil_id INTEGER,
            titulo TEXT NOT NULL,
            tipo_doc TEXT NOT NULL,
            nome_arquivo TEXT NOT NULL,
            data_envio TEXT NOT NULL,
            FOREIGN KEY (perfil_id) REFERENCES perfis(id)
        )
    """)
    
    conn.commit()
    conn.close()

def inserir_dados_iniciais():
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM perfis")
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            "INSERT INTO perfis (nome, tipo, moeda, documento) VALUES (?, ?, ?, ?)",
            ("Minha Empresa PJ", "PJ", "BRL", "00.000.000/0001-00")
        )
        perfil_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO contas (perfil_id, nome, tipo, saldo_inicial) VALUES (?, ?, ?, ?)",
            (perfil_id, "Conta Principal BRL", "Conta Corrente", 0.0)
        )
        conn.commit()
    conn.close()