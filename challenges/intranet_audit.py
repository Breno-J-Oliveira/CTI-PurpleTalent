"""Fictional publication audit. The guest serves immutable evidence."""
import hashlib
import os
from flask import Flask, Response

app = Flask(__name__)
flag = os.environ['FLAG']
documents = (
    ('RH-218', 'Escala da equipe'),
    ('OPS-406', 'Inventário de estações'),
    ('SUP-107', 'Relatório de atendimento'),
)
target = hashlib.sha256(flag.encode()).digest()[0] % len(documents)
references = tuple(
    flag if index == target else 'CTF{' + hashlib.sha256(f'{flag}:{index}'.encode()).hexdigest()[:16] + '}'
    for index in range(len(documents))
)

@app.get('/health')
def health():
    return {'status': 'ok'}

@app.get('/')
def overview():
    return Response(
        'Auditoria de publicações\nTodos os documentos e eventos deste caso são fictícios.\n'
        'Compare o catálogo aprovado, o registro de publicação e as referências de revisão.\n',
        mimetype='text/plain',
    )

@app.get('/catalogo')
def catalog():
    return Response(
        'Documento | Título | Visibilidade aprovada\n' +
        '\n'.join(f'{code} | {name} | interna' for code, name in documents),
        mimetype='text/plain',
    )

@app.get('/publicacoes')
def publications():
    return Response(
        'Horário | Documento | Canal aplicado\n' +
        '\n'.join(f'09:0{index} | {code} | {"público" if index == target else "interno"}'
                  for index, (code, _) in enumerate(documents)),
        mimetype='text/plain',
    )

@app.get('/revisoes')
def revisions():
    return Response(
        'Documento | Referência de revisão\n' +
        '\n'.join(f'{code} | {reference}' for (code, _), reference in zip(documents, references)),
        mimetype='text/plain',
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
