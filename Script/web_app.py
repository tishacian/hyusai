import streamlit as st
import LLM_pipline as llm
import tempfile


st.set_page_config(layout='wide',page_title='Questions Answering APP')
def main(embd_name,llm_name):
    st.title('PDF Question Answer Web-App')

    uploaded_file=st.file_uploader("Upload your PDF File Here",type=['pdf'])

    if uploaded_file is not None:

        question = st.text_input("Enter your question:")
        if st.button("Show Q and A"):
            filepath =uploaded_file.name
            with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
                tmp_file.write(uploaded_file.read())
                filepath = tmp_file.name
            answer = llm.llm_reply(question,filepath,embd_name,llm_name)
            #answer = ans_chain.run(question)
            st.text("____Answer____")
            st.text(answer)


if __name__ == '__main__':
    embd_name="sentence-transformers/all-mpnet-base-v2"
    llm_name="MBZUAI/LaMini-Flan-T5-248M"
    
    main(embd_name,llm_name)