import Footer from "../components/Footer.jsx"

/* The page frame: page, footer.

   The header is no longer rendered anywhere. The homepage hero carries its own
   navigation (the two calls to action), the upload page opens straight into the
   instrument, and the documents workspace navigates through its own sidebar. The
   header component is kept in the tree for when it is wanted again.

   The chat workspaces (/upload and /documents) pass footer={false}: once a
   conversation starts the page belongs to the document and the answer, and a
   marketing footer under a chat box is furniture in the way. */

const Form = ({children, footer = true}) => {

    return(
        <>
            <div>
                {children}
            </div>
        {footer ? <Footer/> : null}
        </>
    )
}

export default Form
