import Header from './Header'
import Sidebar from './Sidebar'

function Layout({ children }) {
  return (
    <div className="min-h-screen bg-[#0c1222]">
      <Header />
      <div className="flex">
        <Sidebar />
        <main className="flex-1 p-6 pb-12 ml-72 mt-16">
          {children}
        </main>
      </div>
    </div>
  )
}

export default Layout
