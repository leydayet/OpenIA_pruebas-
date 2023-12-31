import os
from glob import glob
import streamlit as st

from dotenv import load_dotenv
from PyPDF2 import PdfReader

from langchain.llms import OpenAI
from langchain.chat_models import ChatOpenAI
from langchain.callbacks import get_openai_callback

from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.vectorstores import Qdrant
from langchain.chains import RetrievalQA

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

QDRANT_PATH = "./local_qdrant"
COLLECTION_NAME = "my_collection_2"


def init_page():
    st.set_page_config(
        page_title="Resúmenes de PDFs",
        page_icon="💻"
    )
    st.sidebar.title("Opciones")
    st.session_state.costs = []


def select_model():
    model = st.sidebar.radio("Modelo:", ("GPT-3.5", "GPT-3.5-16k", "GPT-4"))
    if model == "GPT-3.5":
        st.session_state.model_name = "gpt-3.5-turbo"
    elif model == "GPT-3.5":
        st.session_state.model_name = "gpt-3.5-turbo-16k"
    else:
        st.session_state.model_name = "gpt-4"
    
    # 300: The number of tokens for instructions outside the main text
    st.session_state.max_token = OpenAI.modelname_to_contextsize(st.session_state.model_name) - 300
    return ChatOpenAI(temperature=0, model_name=st.session_state.model_name)


def get_pdf_text():
    uploaded_file = st.file_uploader(
        label='Carga tu PDF aquí:',
        type='pdf'
    )
    if uploaded_file:
        pdf_reader = PdfReader(uploaded_file)
        text = '\n\n'.join([page.extract_text() for page in pdf_reader.pages])
        text_splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
            model_name="text-embedding-ada-002",
            # El tamaño de fragmento apropiado (chunk_size) debe ajustarse según el PDF que se consulta.
            # Si es demasiado grande, es posible que no pueda hacer referencia a información de varias partes al responder preguntas.
            # Por otro lado, si es demasiado pequeño, es posible que un fragmento no contenga suficiente información contextual.
            chunk_size=500,
            chunk_overlap=0,
        )
        return text_splitter.split_text(text)
    else:
        return None


def load_qdrant():
    client = QdrantClient(path=QDRANT_PATH)

    # Obtener todos los nombres de las colecciones.
    collections = client.get_collections().collections
    collection_names = [collection.name for collection in collections]

    # Si la colección no existe, se crea.
    if COLLECTION_NAME not in collection_names:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=1536, distance=Distance.COSINE),
        )
        print('Colección creada')

    return Qdrant(
        client=client,
        collection_name=COLLECTION_NAME, 
        embeddings=OpenAIEmbeddings()
    )


def build_vector_store(pdf_text):
    qdrant = load_qdrant()
    qdrant.add_texts(pdf_text)

    # Como opción alternativa, la base de datos vectorial se inicializará cada vez.
    # Qdrant.from_texts(
    #     pdf_text,
    #     OpenAIEmbeddings(),
    #     path="./local_qdrant",
    #     collection_name="my_documents",
    # )


def build_qa_model(llm):
    qdrant = load_qdrant()
    retriever = qdrant.as_retriever(
        # También hay "mmr", "similarity_score_threshold" y otros.
        search_type="similarity",
        # ¿Cuántos documentos recuperar? (predeterminado: 4)
        search_kwargs={"k":10}
    )
    return RetrievalQA.from_chain_type(
        llm=llm,
        chain_type="stuff", 
        retriever=retriever,
        return_source_documents=True,
        verbose=True
    )


def page_pdf_upload_and_build_vector_db():
    st.title("Cargar PDF")
    container = st.container()
    with container:
        pdf_text = get_pdf_text()
        if pdf_text:
            with st.spinner("Cargando PDF ..."):
                build_vector_store(pdf_text)


def ask(qa, query):
    with get_openai_callback() as cb:
        # query / result / source_documents
        answer = qa(query)

    return answer, cb.total_cost


def page_ask_my_pdf():
    st.title("Consultar PDF")

    llm = select_model()
    container = st.container()
    response_container = st.container()

    with container:
        query = st.text_input("Prompt: ", key="input")
        if not query:
            answer = None
        else:
            qa = build_qa_model(llm)
            if qa:
                with st.spinner("El Asistente Virtual está escribiendo..."):
                    answer, cost = ask(qa, query)
                st.session_state.costs.append(cost)
            else:
                answer = None

        if answer:
            with response_container:
                st.markdown("## Respuesta")
                st.write(answer)


def main():
    init_page()

    selection = st.sidebar.radio("Ir a:", ["Cargar PDF", "Consultar PDF"])
    if selection == "Cargar PDF":
        page_pdf_upload_and_build_vector_db()
    elif selection == "Consultar PDF":
        page_ask_my_pdf()

    costs = st.session_state.get('costs', [])
    st.sidebar.markdown("## Estimación de Costos")
    st.sidebar.markdown(f"Costo total en dólares: ${sum(costs):.5f}")
    for cost in costs:
        st.sidebar.markdown(f"- ${cost:.5f}")


if __name__ == '__main__':
    main()