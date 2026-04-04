import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"

export default function BadgeWall() {
  const cards = props.cards || []
  const stats = props.stats || {}

  const colorMap = {
    green: "bg-green-50 border-green-200",
    yellow: "bg-yellow-50 border-yellow-200",
    red: "bg-red-50 border-red-200",
  }

  return (
    <Card className="w-full">
      <CardHeader className="pb-3">
        <CardTitle className="text-lg">🏆 求职总览</CardTitle>
        <div className="flex gap-4 text-sm text-muted-foreground">
          <span>进行中 <strong className="text-foreground">{stats.active || 0}</strong></span>
          <span>本周新增 <strong className="text-foreground">{stats.new_this_week || 0}</strong></span>
          <span>面试 <strong className="text-foreground">{stats.interviews || 0}</strong></span>
          <span>Offer <strong className="text-foreground">{stats.offers || 0}</strong></span>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {cards.map((card, i) => (
            <div key={i} className={`rounded-xl border p-4 ${colorMap[card.color] || "bg-muted"}`}>
              <p className="font-semibold text-sm">{card.title}</p>
              <p className="text-xs text-muted-foreground mt-0.5">{card.company}</p>
              <div className="flex items-center justify-between mt-3">
                <Badge variant="secondary" className="text-xs">匹配 {card.score}</Badge>
                <span className="text-xs text-muted-foreground">{card.stage}</span>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
