
from pathlib import Path
import sqlite3
from datetime import date

from flask import (
    Flask, g, render_template, request,
    redirect, url_for, flash
)

app = Flask(__name__, instance_relative_config=True)
app.config["SECRET_KEY"] = "troque-por-uma-chave-segura"
DB_PATH = Path(app.instance_path) / "biblioteca.db"


def conectar():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def fechar_banco(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def consultar(sql, parametros=()):
    return conectar().execute(sql, parametros).fetchall()


def preparar_banco():
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA foreign_keys = ON")

    db.executescript("""
        CREATE TABLE IF NOT EXISTS livros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            autor TEXT NOT NULL,
            categoria TEXT NOT NULL DEFAULT '',
            quantidade INTEGER NOT NULL CHECK (quantidade > 0)
        );

        CREATE TABLE IF NOT EXISTS alunos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            matricula TEXT NOT NULL UNIQUE,
            turma TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS emprestimos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            livro_id INTEGER NOT NULL REFERENCES livros(id),
            aluno_id INTEGER NOT NULL REFERENCES alunos(id),
            data_emprestimo TEXT NOT NULL,
            data_prevista TEXT NOT NULL,
            data_devolucao TEXT
        );
    """)

    db.commit()
    db.close()


@app.route("/")
def inicio():
    db = conectar()
    hoje = date.today().isoformat()

    total_livros = db.execute(
        "SELECT COALESCE(SUM(quantidade), 0) FROM livros"
    ).fetchone()[0]

    total_alunos = db.execute(
        "SELECT COUNT(*) FROM alunos"
    ).fetchone()[0]

    ativos = db.execute(
        "SELECT COUNT(*) FROM emprestimos "
        "WHERE data_devolucao IS NULL"
    ).fetchone()[0]

    atrasados = db.execute(
        "SELECT COUNT(*) FROM emprestimos "
        "WHERE data_devolucao IS NULL AND data_prevista < ?",
        (hoje,)
    ).fetchone()[0]

    return render_template(
        "inicio.html",
        total_livros=total_livros,
        total_alunos=total_alunos,
        ativos=ativos,
        atrasados=atrasados
    )


@app.route("/livros", methods=["GET", "POST"])
def livros():
    if request.method == "POST":
        titulo = request.form.get("titulo", "").strip()
        autor = request.form.get("autor", "").strip()
        categoria = request.form.get("categoria", "").strip()

        try:
            quantidade = int(request.form.get("quantidade", "0"))
        except ValueError:
            quantidade = 0

        if not titulo or not autor or quantidade < 1:
            flash("Preencha os dados corretamente.")
        else:
            conectar().execute(
                "INSERT INTO livros "
                "(titulo, autor, categoria, quantidade) "
                "VALUES (?, ?, ?, ?)",
                (titulo, autor, categoria, quantidade)
            )
            conectar().commit()
            flash("Livro cadastrado com sucesso!")
            return redirect(url_for("livros"))

    termo = request.args.get("q", "").strip()

    lista = consultar("""
        SELECT l.*,
          l.quantidade - (
            SELECT COUNT(*) FROM emprestimos e
            WHERE e.livro_id = l.id
              AND e.data_devolucao IS NULL
          ) AS disponiveis
        FROM livros l
        WHERE l.titulo LIKE ? OR l.autor LIKE ?
        ORDER BY l.titulo
    """, (f"%{termo}%", f"%{termo}%"))

    return render_template(
        "livros.html", livros=lista, termo=termo
    )


@app.route("/alunos", methods=["GET", "POST"])
def alunos():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        matricula = request.form.get("matricula", "").strip()
        turma = request.form.get("turma", "").strip()

        if not nome or not matricula or not turma:
            flash("Preencha todos os campos.")
        else:
            try:
                conectar().execute(
                    "INSERT INTO alunos (nome, matricula, turma) "
                    "VALUES (?, ?, ?)",
                    (nome, matricula, turma)
                )
                conectar().commit()
                flash("Aluno cadastrado com sucesso!")
                return redirect(url_for("alunos"))
            except sqlite3.IntegrityError:
                conectar().rollback()
                flash("Esta matrícula já está cadastrada.")

    lista = consultar("SELECT * FROM alunos ORDER BY nome")

    return render_template("alunos.html", alunos=lista)


@app.route("/emprestimos", methods=["GET", "POST"])
def emprestimos():
    hoje = date.today().isoformat()

    if request.method == "POST":
        livro_id = request.form.get("livro_id", type=int)
        aluno_id = request.form.get("aluno_id", type=int)
        prazo = request.form.get("data_prevista", "")

        if not livro_id or not aluno_id or not prazo:
            flash("Preencha todos os campos.")
        elif prazo < hoje:
            flash("A data prevista não pode ser anterior a hoje.")
        else:
            db = conectar()

            livro = db.execute(
                "SELECT * FROM livros WHERE id = ?", (livro_id,)
            ).fetchone()

            aluno = db.execute(
                "SELECT * FROM alunos WHERE id = ?", (aluno_id,)
            ).fetchone()

            if not livro or not aluno:
                flash("Livro ou aluno não encontrado.")
            else:
                ativos = db.execute(
                    "SELECT COUNT(*) FROM emprestimos "
                    "WHERE livro_id = ? AND data_devolucao IS NULL",
                    (livro_id,)
                ).fetchone()[0]

                if ativos >= livro["quantidade"]:
                    flash("Não há exemplares disponíveis.")
                else:
                    db.execute("""
                        INSERT INTO emprestimos
                        (livro_id, aluno_id, data_emprestimo,
                         data_prevista)
                        VALUES (?, ?, ?, ?)
                    """, (livro_id, aluno_id, hoje, prazo))
                    db.commit()
                    flash("Empréstimo registrado!")
                    return redirect(url_for("emprestimos"))

    livros_disponiveis = consultar("""
        SELECT l.id, l.titulo,
          l.quantidade - (
            SELECT COUNT(*) FROM emprestimos e
            WHERE e.livro_id = l.id
              AND e.data_devolucao IS NULL
          ) AS disponiveis
        FROM livros l
        WHERE l.quantidade > (
            SELECT COUNT(*) FROM emprestimos e
            WHERE e.livro_id = l.id
              AND e.data_devolucao IS NULL
        )
        ORDER BY l.titulo
    """)

    estudantes = consultar("SELECT * FROM alunos ORDER BY nome")

    lista = consultar("""
        SELECT e.*, l.titulo, a.nome, a.matricula, a.turma
        FROM emprestimos e
        JOIN livros l ON l.id = e.livro_id
        JOIN alunos a ON a.id = e.aluno_id
        ORDER BY e.id DESC
    """)

    return render_template(
        "emprestimos.html",
        livros=livros_disponiveis,
        alunos=estudantes,
        emprestimos=lista,
        hoje=hoje
    )


@app.route("/devolver/<int:emprestimo_id>", methods=["POST"])
def devolver(emprestimo_id):
    db = conectar()

    registro = db.execute(
        "SELECT * FROM emprestimos WHERE id = ?",
        (emprestimo_id,)
    ).fetchone()

    if registro is None:
        flash("Empréstimo não encontrado.")
    elif registro["data_devolucao"] is not None:
        flash("Este empréstimo já foi devolvido.")
    else:
        db.execute(
            "UPDATE emprestimos SET data_devolucao = ? WHERE id = ?",
            (date.today().isoformat(), emprestimo_id)
        )
        db.commit()
        flash("Devolução registrada!")

    return redirect(url_for("emprestimos"))


@app.route("/relatorios")
def relatorios():
    hoje = date.today().isoformat()

    ativos = consultar("""
        SELECT l.titulo, a.nome, a.turma,
               e.data_emprestimo, e.data_prevista
        FROM emprestimos e
        JOIN livros l ON l.id = e.livro_id
        JOIN alunos a ON a.id = e.aluno_id
        WHERE e.data_devolucao IS NULL
        ORDER BY e.data_prevista
    """)

    atrasados = [
        e for e in ativos if e["data_prevista"] < hoje
    ]

    devolvidos = consultar("""
        SELECT l.titulo, a.nome, e.data_emprestimo,
               e.data_devolucao
        FROM emprestimos e
        JOIN livros l ON l.id = e.livro_id
        JOIN alunos a ON a.id = e.aluno_id
        WHERE e.data_devolucao IS NOT NULL
        ORDER BY e.data_devolucao DESC
    """)

    return render_template(
        "relatorios.html",
        ativos=ativos,
        atrasados=atrasados,
        devolvidos=devolvidos
    )


preparar_banco()

if __name__ == "__main__":
    app.run(debug=True)
