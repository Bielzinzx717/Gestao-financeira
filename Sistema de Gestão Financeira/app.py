from flask import Flask, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from extensions import db, login_manager
from models import Usuario, Transacao
from datetime import datetime
import os
from sqlalchemy import func, case  # Para relatório mensal

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-key')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///finance.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return Usuario.query.get(int(user_id))

with app.app_context():
    db.create_all()

@app.route('/')
def home():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        nome = request.form['nome']
        email = request.form['email']
        senha = request.form['senha']

        if Usuario.query.filter_by(email=email).first():
            flash('E-mail já cadastrado!', 'error')
            return redirect(url_for('register'))

        try:
            novo_usuario = Usuario(nome=nome, email=email)
            novo_usuario.set_password(senha)
            db.session.add(novo_usuario)
            db.session.commit()
            flash('Cadastro realizado com sucesso! Faça o login.', 'success')
            return redirect(url_for('login'))
        except ValueError as e:
            flash(str(e), 'error')

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        senha = request.form['senha']
        usuario = Usuario.query.filter_by(email=email).first()

        if usuario and usuario.check_password(senha):
            login_user(usuario)
            flash('Login realizado com sucesso!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('E-mail ou senha inválidos.', 'error')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Você saiu da sua conta.', 'success')
    return redirect(url_for('login'))

@app.route('/dashboard', methods=['GET'])
@login_required
def dashboard():
    data_inicial_str = request.args.get('data_inicial')
    data_final_str = request.args.get('data_final')
    filtro_tipo = request.args.get('tipo')
    filtro_categoria = request.args.get('categoria')
    filtro_busca = request.args.get('busca')

    data_inicial = None
    data_final = None

    query_base = Transacao.query.filter_by(usuario_id=current_user.id)
    query_filtrada = query_base

    if data_inicial_str:
        try:
            data_inicial = datetime.strptime(data_inicial_str, '%Y-%m-%d').date()
            query_filtrada = query_filtrada.filter(Transacao.data >= data_inicial)
        except ValueError:
            flash('Formato de Data Inicial inválido.', 'error')
            data_inicial_str = None

    if data_final_str:
        try:
            data_final = datetime.strptime(data_final_str, '%Y-%m-%d').date()
            query_filtrada = query_filtrada.filter(Transacao.data <= data_final)
        except ValueError:
            flash('Formato de Data Final inválido.', 'error')
            data_final_str = None

    if filtro_tipo and filtro_tipo != 'todos':
        query_filtrada = query_filtrada.filter(Transacao.tipo == filtro_tipo)
    
    if filtro_categoria and filtro_categoria != 'todas':
        query_filtrada = query_filtrada.filter(Transacao.categoria == filtro_categoria)
    
    if filtro_busca:
        query_filtrada = query_filtrada.filter(Transacao.descricao.ilike(f'%{filtro_busca}%'))

    categorias_disponiveis = db.session.query(Transacao.categoria).filter_by(usuario_id=current_user.id).distinct().all()
    categorias_disponiveis = [c[0] for c in categorias_disponiveis]

    if data_inicial_str and data_final_str:
        transacoes = query_filtrada.order_by(Transacao.data.desc()).all()
        total_receitas = sum(t.valor for t in transacoes if t.tipo == 'receita')
        total_despesas = sum(t.valor for t in transacoes if t.tipo == 'despesa')
        saldo = total_receitas - total_despesas

        return render_template('dashboard.html',
                               transacoes=transacoes,
                               total_receitas=total_receitas,
                               total_despesas=total_despesas,
                               saldo=saldo,
                               relatorio_mensal=None,
                               data_inicial_str=data_inicial_str,
                               data_final_str=data_final_str,
                               filtro_tipo=filtro_tipo,
                               filtro_categoria=filtro_categoria,
                               filtro_busca=filtro_busca,
                               categorias_disponiveis=categorias_disponiveis)

    else:
        # Relatório mensal padrão
        relatorio_mensal_raw = db.session.query(
            func.strftime('%Y-%m', Transacao.data).label('mes_ano'),
            func.sum(case((Transacao.tipo == 'receita', Transacao.valor), else_=0)).label('total_receitas'),
            func.sum(case((Transacao.tipo == 'despesa', Transacao.valor), else_=0)).label('total_despesas')
        ).filter_by(usuario_id=current_user.id).group_by('mes_ano').order_by(func.strftime('%Y-%m', Transacao.data).desc()).all()

        relatorio_mensal = []
        total_receitas_geral = 0
        total_despesas_geral = 0

        for mes_ano, receitas, despesas in relatorio_mensal_raw:
            saldo_mes = receitas - despesas
            relatorio_mensal.append({
                'mes_ano': mes_ano,
                'total_receitas': receitas,
                'total_despesas': despesas,
                'saldo': saldo_mes
            })
            total_receitas_geral += receitas
            total_despesas_geral += despesas

        saldo_geral = total_receitas_geral - total_despesas_geral

        transacoes = query_filtrada.order_by(Transacao.data.desc()).limit(10).all()
        
        if filtro_tipo or filtro_categoria or filtro_busca:
            todas_transacoes_filtradas = query_filtrada.all()
            total_receitas_geral = sum(t.valor for t in todas_transacoes_filtradas if t.tipo == 'receita')
            total_despesas_geral = sum(t.valor for t in todas_transacoes_filtradas if t.tipo == 'despesa')
            saldo_geral = total_receitas_geral - total_despesas_geral

        return render_template('dashboard.html',
                               transacoes=transacoes,
                               total_receitas=total_receitas_geral,
                               total_despesas=total_despesas_geral,
                               saldo=saldo_geral,
                               relatorio_mensal=relatorio_mensal,
                               data_inicial_str=None,
                               data_final_str=None,
                               filtro_tipo=filtro_tipo,
                               filtro_categoria=filtro_categoria,
                               filtro_busca=filtro_busca,
                               categorias_disponiveis=categorias_disponiveis)

@app.route('/nova', methods=['GET', 'POST'])
@login_required
def nova_transacao():
    if request.method == 'POST':
        descricao = request.form['descricao']
        valor = float(request.form['valor'])
        tipo = request.form['tipo']
        categoria = request.form['categoria']
        data = datetime.strptime(request.form['data'], '%Y-%m-%d')

        transacao = Transacao(
            descricao=descricao,
            valor=valor,
            tipo=tipo,
            categoria=categoria,
            data=data,
            usuario_id=current_user.id
        )
        db.session.add(transacao)
        db.session.commit()
        flash('Transação adicionada!', 'success')
        return redirect(url_for('dashboard'))

    return render_template('transaction_form.html')

@app.route('/delete/<int:id>')
@login_required
def delete(id):
    transacao = Transacao.query.get_or_404(id)
    if transacao.usuario_id != current_user.id:
        flash('Acesso negado.', 'error')
        return redirect(url_for('dashboard'))

    db.session.delete(transacao)
    db.session.commit()
    flash('Transação excluída.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_transacao(id):
    transacao = Transacao.query.get_or_404(id)
    
    # Verificar se a transação pertence ao usuário atual
    if transacao.usuario_id != current_user.id:
        flash('Acesso negado.', 'error')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        transacao.descricao = request.form['descricao']
        transacao.valor = float(request.form['valor'])
        transacao.tipo = request.form['tipo']
        transacao.categoria = request.form['categoria']
        transacao.data = datetime.strptime(request.form['data'], '%Y-%m-%d')
        
        db.session.commit()
        flash('Transação atualizada com sucesso!', 'success')
        return redirect(url_for('dashboard'))
    
    return render_template('transaction_form.html', transacao=transacao)

if __name__ == '__main__':
    app.run(debug=True)
