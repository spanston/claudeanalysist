import { Routes, Route } from 'react-router'
import Home from './pages/Home'
import PostPage from './pages/Post'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/post/:id" element={<PostPage />} />
    </Routes>
  )
}
