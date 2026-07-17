import { Navigate, useParams } from "react-router-dom";

/** 兼容旧板块详情链接；实际研究统一在单页工作台完成。 */
export function Component() {
  const { name = "" } = useParams();
  return <Navigate to={`/sectors?sector=${encodeURIComponent(decodeURIComponent(name))}`} replace />;
}
