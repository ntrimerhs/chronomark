import Header from "../components/header.jsx"
import Footer from "../components/Footer.jsx"

/* The page frame: header, page, footer.

   The landing page carries its own top bar, so it passes header={false}; every
   other route still renders the site header. The chat workspaces (/upload and
   /documents) pass footer={false}: once a conversation starts the page belongs to
   the document and the answer, and a marketing footer under a chat box is
   furniture in the way. */

const Form = ({children, footer = true, header = true}) => {

    return(
        <>
        {header ? <Header/> : null}
            <div>
                {children}
            </div>
        {footer ? <Footer/> : null}
        </>
    )
}

export default Form
