from sqlalchemy import create_engine, Column, Integer, String, Float, Date, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.sql import func
import datetime

DATABASE_URL = "sqlite:///./mister_data.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Player(Base):
    __tablename__ = "players"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    team = Column(String)
    position = Column(String)
    status = Column(String, default="ok")
    trend = Column(String, default="flat")
    streak = Column(String)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    history = relationship("PlayerHistory", back_populates="player")
    
class PlayerHistory(Base):
    __tablename__ = "player_history"
    __table_args__ = (UniqueConstraint('player_id', 'date', name='uix_1'),)
    
    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(Integer, ForeignKey("players.id"))
    points = Column(Integer, default=0)
    average_points = Column(Float, default=0.0)
    value = Column(Integer, default=0)
    trend = Column(String, default="flat")
    streak = Column(String)
    date = Column(Date, default=datetime.date.today)
    player = relationship("Player", back_populates="history")
    
class MySquad(Base):
    __tablename__ = "my_squad"
    player_id = Column(Integer, ForeignKey("players.id"), primary_key=True)
    purchase_price = Column(Integer)
    player = relationship("Player")

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def upsert_player(db, player_data):
    """
    Inserts a new player or updates an existing one.
    This ensures that new players added to the game are handled properly.
    """
    player_id = player_data['id']
    streak_str = ",".join(map(str, player_data.get('streak', [])))
    trend = player_data.get('trend', 'flat')
    
    # Check if player exists
    player = db.query(Player).filter(Player.id == player_id).first()
    if player:
        player.name = player_data['name']
        player.team = player_data.get('team', '')
        player.position = player_data.get('position', '')
        player.status = player_data.get('status', 'ok')
        player.trend = trend
        player.streak = streak_str
    else:
        player = Player(
            id=player_id,
            name=player_data['name'],
            team=player_data.get('team', ''),
            position=player_data.get('position', ''),
            status=player_data.get('status', 'ok'),
            trend=trend,
            streak=streak_str
        )
        db.add(player)
    
    db.commit()
    db.refresh(player)
    
    # Check if history for today exists
    today = datetime.date.today()
    history = db.query(PlayerHistory).filter(
        PlayerHistory.player_id == player_id,
        PlayerHistory.date == today
    ).first()
    
    if not history:
        history = PlayerHistory(
            player_id=player_id,
            points=player_data.get('points', 0),
            average_points=player_data.get('average_points', 0.0),
            value=player_data.get('value', 0),
            trend=trend,
            streak=streak_str,
            date=today
        )
        db.add(history)
        db.commit()
        
    return player
