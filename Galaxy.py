def nave_estelar_cercana(sensado:list[int], p:int) -> bool:
    """
    Requiere: p >= 0, los elementos en sensado >= 0
    Devuelve: True si hay una nave muy cercana. Es decir a <= p. 
    """
    i:int = 0
    bol:bool = False
    while i < len(sensado):
        if sensado[i] <= p:
           bol = True
        i=i+1
    return bol
    
sensado = [300, 300, 100]
p = 10
print (nave_estelar_cercana(sensado, p))