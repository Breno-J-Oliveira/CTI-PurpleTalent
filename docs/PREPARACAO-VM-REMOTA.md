# Preparação do executor de VMs remotas

Os módulos experimentais remote_worker.py e scripts/remote_worker.py implementam uma fila e um executor autenticado, com operações restritas de iniciar e encerrar. Ainda não estão ligados ao aplicativo publicado. As credenciais devem ser criadas fora do Git, e o journal deve ficar em pasta privada.

A versão atual espera VirtualBox, Vagrant e uma VM base. A inspeção neste computador encontrou esses componentes ausentes e o Windows reportou hypervisor ativo sem recursos de virtualização disponíveis ao sistema. Existe runtime QEMU de trabalho anterior no D:, mas a integração desta versão com ele não foi implementada.

Pendências obrigatórias antes de ativar: integração transacional com desafio e permissões por equipe, acesso HTTP à VM autenticado por participante e com isolamento, estado e reconciliação em caso de queda, limite de recursos, testes com VirtualBox/QEMU real e verificação da conexão no PythonAnywhere. A fila bloqueia após lease interrompido até haver reconciliação. Flags são removidas logicamente após confirmação; SQLite pode manter dados em páginas ou journal.

Não habilitar o laboratório público nem expor porta local enquanto estes testes estiverem pendentes.
