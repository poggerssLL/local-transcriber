# Local Transcriber: instalar e usar, passo a passo

O Local Transcriber transforma gravações de áudio ou vídeo em texto. Você organiza
as gravações por matéria, acompanha a transcrição e baixa o texto quando terminar.
O aplicativo abre no navegador, mas funciona no seu computador.

## 1. O que você precisa

- Um computador com Windows 10 ou Windows 11 de 64 bits, com processador Intel
  ou AMD. Computadores com Windows ARM, Linux e macOS ainda não foram homologados.
- O arquivo de instalação, com nome parecido com
  **LocalTranscriber-Setup-0.7.1-windows-x64.exe**. O número da versão pode mudar.
- Internet para baixar o instalador e, depois, o modelo de transcrição.
- Espaço livre para o aplicativo, os modelos e suas gravações.

**Você não precisa baixar o repositório inteiro, instalar Python ou usar comandos
para instalar e começar a transcrever pelo Setup.**

Neste momento, o instalador deve ser fornecido pelo responsável pelo projeto.
Ainda não há uma versão do instalador publicada na área de downloads do GitHub.
O botão **Code → Download ZIP** baixa o código do projeto, e não o instalador.

## 2. Instalar no Windows

1. Salve o arquivo **LocalTranscriber-Setup-…-windows-x64.exe** no computador
   em que deseja usar o aplicativo.
2. Abra a pasta **Downloads**, ou a pasta onde você salvou o arquivo.
3. Dê dois cliques no arquivo Setup.
4. Leia as instruções e a licença que aparecem na tela e prossiga se concordar.
5. Siga as etapas até terminar a instalação.
6. Se aparecer uma solicitação para instalar o **Microsoft Visual C++ Runtime**,
   esse é um componente necessário ao aplicativo. Sua instalação pode pedir a
   senha ou autorização do administrador do computador.
7. Ao terminar, deixe marcada a opção **Abrir Local Transcriber e preparar modelos**.

O instalador prepara o programa e seus componentes. A base de dados será criada
automaticamente quando o aplicativo abrir. Você não precisa criar um banco manualmente.

Se o Windows bloquear o arquivo ou mostrar um aviso que você não reconhece,
anote a mensagem e confirme a origem do arquivo com quem forneceu o instalador.

### Se você já usa o Local Transcriber neste computador

Feche a versão que está aberta antes de instalar ou abrir outra.
As versões do mesmo usuário usam a mesma biblioteca. Instalar em outra pasta
não cria uma biblioteca de teste separada. Para testar sem usar seus dados reais,
peça orientação para preparar um teste isolado antes de abrir a nova versão.

## 3. Abrir o aplicativo

Nas próximas vezes, abra o menu **Iniciar** do Windows, procure
**Local Transcriber** e clique no aplicativo.

Ele abre uma janela com mensagens e uma página no navegador.
**Mantenha a janela com mensagens aberta enquanto usa o programa.**
Você pode minimizá-la. Fechar apenas a página do navegador não encerra o aplicativo.

Se a página não abrir sozinha, copie o endereço que aparece na janela do programa
e cole na barra de endereços do navegador. Normalmente ele começa com
`http://127.0.0.1:`. Esse endereço aponta para o seu próprio computador.

## 4. Preparar a transcrição pela primeira vez

O aplicativo precisa de um **modelo**, que é o arquivo de inteligência artificial
usado para reconhecer a fala. Ele é baixado separadamente e fica no computador.

1. Abra a aba **Modelos**.
2. Encontre **small**, uma opção inicial para transcrever em português.
3. Clique em **Baixar small**.
4. Confirme o download. Ele precisa de internet e espaço em disco.
5. Aguarde aparecer **Instalado**. Mantenha o aplicativo aberto durante o download.

Você só precisa baixar esse modelo uma vez por biblioteca. Depois, a transcrição
pode funcionar sem internet. O aplicativo não baixa modelos sem sua confirmação.
Se aparecer uma falha, confira a conexão e o espaço livre e clique em
**Tentar novamente**.

## 5. Transcrever sua primeira gravação

Comece com um áudio curto para se familiarizar com o programa.

1. Abra **Matérias** e crie uma matéria, por exemplo **Álgebra Linear**.
2. Abra **Biblioteca**.
3. No formulário de importação, escolha o áudio ou vídeo no seu computador.
4. Escreva um título que ajude a encontrar a gravação depois, por exemplo
   **Álgebra — aula de 21 de agosto**.
5. Escolha a matéria e a data da aula.
6. Clique em **Importar Arquivo** e aguarde a gravação aparecer na biblioteca.
7. Clique em **Transcrever** na linha dessa gravação.
8. Escolha o modelo **small**, já instalado, e o idioma **Português**, quando
   essa for a língua da gravação.
9. Revise as opções e confirme o envio para transcrição.

O perfil **CPU** usa o processador e pode funcionar sem uma placa de vídeo
preparada para inteligência artificial, embora possa ser mais lento.
O perfil **CUDA** exige uma GPU NVIDIA e os componentes compatíveis instalados.
Ter uma placa de vídeo não garante que ela funcione com o aplicativo atual.
O uso de um desktop AMD como worker remoto está em preparação e não faz parte
deste instalador. Você pode manter as demais opções com os valores iniciais.

A importação faz uma cópia da gravação para a biblioteca do aplicativo. Por isso,
o programa precisa de espaço em disco além daquele ocupado pelo arquivo original.

## 6. Acompanhar o andamento

Abra a aba **Fila** para ver as transcrições e seu estado:

| Estado | O que significa |
| --- | --- |
| Enfileirado | Está esperando a vez de começar. |
| Em andamento | O aplicativo está processando a gravação. |
| Transcrição pronta / Concluído | O texto já pode ser aberto. |
| Falhou | Algo impediu a conclusão. Leia a mensagem antes de tentar novamente. |
| Cancelado | A execução foi interrompida. |

O tempo varia com a duração do áudio, o modelo e o computador. A fila processa
uma transcrição por vez. Recarregar a página não cancela o trabalho.
Se precisar parar um trabalho, use **Cancelar** na interface.

Hoje, **Tentar novamente** repete o trabalho com as configurações anteriores.
A seleção de outro computador e a reconfiguração nesse botão ainda não estão disponíveis.

## 7. Ler e baixar o texto

1. Quando a transcrição terminar, volte à **Biblioteca**.
2. Clique em **Ler** na gravação concluída.
3. Leia e revise o texto. Você também pode ouvir a gravação e conferir os trechos.
4. Na área de exportação, escolha o formato desejado. Se aparecer **Gerar**,
   clique para preparar o arquivo e iniciar o download.
5. Procure o arquivo na pasta **Downloads** do navegador, salvo se você escolher outra pasta.

| Formato | Para que serve |
| --- | --- |
| TXT | Texto simples, para abrir em editores e copiar para outros programas. |
| Markdown / MD | Texto com formatação simples, útil em aplicativos de notas. |
| SRT ou VTT | Legendas com indicação de tempo, para programas que aceitam esses formatos. |
| JSON | Dados estruturados, geralmente usados por ferramentas técnicas. |

O nome do arquivo usa o título da gravação. Caracteres que não podem ser usados
em nomes de arquivo são adaptados: **Algebra 21/8** vira **Algebra 21-8.md**, por exemplo.
Revise o texto antes de usar, pois nomes próprios, fórmulas e termos técnicos podem conter erros.

## 8. Gerar resumos (opcional)

Transcrever áudio e gerar resumo são recursos diferentes. **Ollama não é necessário
para transcrever.** Para resumos locais, abra a aba **Modelos** e siga as instruções
da seção **Resumos locais com Ollama**. Essa preparação adicional exige instalar
Ollama e baixar o modelo indicado; não acontece automaticamente pelo Setup.

Depois de preparar o Ollama, abra uma transcrição em **Leitura**, escolha **Ollama**
e use **Gerar Resumo**. A transcrição básica não exige conta de IA ou chave de API.

## 9. Encerrar, atualizar ou desinstalar

- **Encerrar:** de preferência, aguarde a transcrição terminar. Volte à janela
  com mensagens do aplicativo e pressione **Ctrl + C**.
- **Atualizar:** feche o aplicativo, abra o novo Setup e escolha **Atualizar**.
- **Desinstalar:** feche o aplicativo, abra o Setup novamente e escolha
  **Desinstalar**. Você também pode usar a lista de aplicativos instalados do Windows.
- **Cancelar a manutenção:** escolha **Cancelar** para sair sem atualizar ou desinstalar.

A desinstalação remove o programa e seus atalhos, mas preserva gravações,
transcrições e modelos. Não é preciso apagar seus dados para atualizar.

## 10. Onde ficam minhas gravações e como guardar uma cópia

Os dados do programa ficam em uma pasta separada. Para abri-la:

1. Pressione **Windows + R**.
2. Cole `%LOCALAPPDATA%\LocalTranscriber` e pressione **Enter**.

A subpasta **media** guarda as cópias dos áudios e vídeos, inclusive os recebidos
por upload remoto. Não mova nem renomeie esses arquivos dentro da biblioteca:
o aplicativo precisa encontrá-los pelos caminhos registrados.

Para guardar uma cópia de segurança, feche o aplicativo e copie a pasta inteira
**LocalTranscriber** para outro local seguro. Ela contém dados pessoais e pode ser
grande. Baixar apenas o TXT ou MD salva o texto, mas não salva toda a biblioteca.

## Se algo não funcionar

| Situação | O que fazer |
| --- | --- |
| Não encontro o Setup | Peça o arquivo `.exe` ao responsável pelo projeto. O ZIP do código não substitui o instalador. |
| O navegador não abriu | Copie o endereço mostrado na janela do aplicativo e abra no navegador. |
| Modelo ausente | Abra Modelos, baixe o modelo escolhido e aguarde Instalado. |
| Download falhou | Confira internet e espaço livre e use Tentar novamente. |
| Erro de DLL ou Visual C++ | Execute o Setup para preparar os componentes necessários; se persistir, envie a mensagem de erro. |
| Erro de CUDA / GPU | A GPU pode não estar preparada. Use CPU se isso atender ao seu uso, ou peça ajuda para configurar a GPU. |
| Serviço já está em execução | Procure a janela do aplicativo que já está aberta. Evite abrir duas versões ao mesmo tempo. |
| Áudio não toca no navegador | Pode ser uma limitação do formato de reprodução. Isso não significa, por si só, que a transcrição falhou. |
| Resumo não funciona | Confira a preparação do Ollama na aba Modelos. A transcrição pode continuar funcionando. |

Ao pedir ajuda, informe a mensagem de erro e o passo em que ela apareceu.
Não envie sua biblioteca inteira, áudios pessoais, senhas ou credenciais.

[Voltar ao README](../README.md) · [Instalação técnica e geração do instalador](INSTALLATION.md)
